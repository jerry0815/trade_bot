# Vol-Targeted Leverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `VolTargetLeverage` strategy that vol-targets leverage (allowing >3× in calm regimes) while keeping the binary trend rule's entry/exit, plus a 1990–2026 screen comparing it against binary-3× and fixed-2×.

**Architecture:** `VolTargetLeverage` subclasses `SMATrendFollowing`, reusing its `in_market` column verbatim and overriding only the leverage — emitting a per-day `target_leverage` the engine already consumes. The vol-sizing is a pure static method (unit-testable without a 200-day SMA warm-up). One additive reporting metric (`avg_leverage`) mirrors the existing `rebalances`. A screen script reuses the existing `calmar`/`sharpe_from_equity` helpers.

**Tech Stack:** Python, NumPy, pandas, pytest. No new dependencies. Network-free tests. Builds on the merged/branch engine that already supports the `target_leverage` column.

## Global Constraints

- **No lookahead:** `target_leverage[t]` uses only data through `t−1`. Realized vol is `.shift(1)`; the inherited `in_market` is already `.shift(1)`.
- **Reuse the binary entry/exit unchanged:** subclass `SMATrendFollowing`; do NOT modify its `_add_indicator_logic`. Only the leverage sizing is new.
- **`target_vol=0.45`, `l_min=1.0`, `vol_window=20` are fixed and untuned** (stated in the finding); only `l_max ∈ {3.0, 4.0, 5.0}` is swept.
- **Additive metric only:** `avg_leverage` must be `NaN` when no `target_leverage` column is present (backward-compat).
- **Success bar:** a config wins only if its Calmar AND Sharpe both materially exceed BOTH binary-3× and fixed-2×. A negative screen is a valid outcome.
- **Screen is a soft UPPER bound** — frictionless, single-path, and vol-targeting rebalances daily; state this in the output note and finding.
- **Repo conventions:** branch `dynamic-leverage-3gear` (continue on it). No `bot.py` change. No model identifier in commits. Keep the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

---

### Task 1: `avg_leverage` reporting metric

Add a mean-in-market-leverage metric to trade stats, parallel to the existing `rebalances`.

**Files:**
- Modify: `backtest/strat_backtest.py` (`Backtester._calculate_trade_stats`)
- Test: `tests/test_vol_target_leverage.py` (create)

**Interfaces:**
- Consumes: input `df`, optionally carrying a `target_leverage` column.
- Produces: the trade-stats dict gains an `"avg_leverage"` float key — mean of `target_leverage` over days where it is `> 0`; `NaN` when the column is absent; `0.0` when the column is present but never positive.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vol_target_leverage.py`:

```python
"""Unit tests for vol-targeted leverage strategy + avg_leverage metric.

Network-free: synthetic frames drive the stats function and the pure
vol-sizing method directly.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester


def _frame(start, in_market, target_leverage=None):
    idx = pd.date_range(start, periods=len(in_market), freq="D")
    n = len(idx)
    data = {
        "in_market": np.asarray(in_market, dtype=bool),
        "BR": np.zeros(n),
        "Daily_Return_1x": np.zeros(n),
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }
    if target_leverage is not None:
        data["target_leverage"] = np.asarray(target_leverage, dtype=float)
    return pd.DataFrame(data, index=idx)


def test_avg_leverage_is_mean_over_in_market_days():
    # in-market leverages: 3, 3, 1.5 -> mean 2.5 (cash days excluded)
    lev = [0.0, 3.0, 3.0, 1.5, 0.0]
    df = _frame("2000-01-01", [x > 0 for x in lev], target_leverage=lev)
    env = Backtester(verbose=False)
    stats = env._calculate_trade_stats(df)
    assert abs(stats["avg_leverage"] - 2.5) < 1e-9


def test_avg_leverage_is_nan_without_target_leverage():
    df = _frame("2000-01-01", [True, True, False])
    env = Backtester(verbose=False)
    stats = env._calculate_trade_stats(df)
    assert math.isnan(stats["avg_leverage"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_vol_target_leverage.py -q`
Expected: FAIL with `KeyError: 'avg_leverage'`.

- [ ] **Step 3: Implement**

In `_calculate_trade_stats`, alongside the existing `rebalances` computation, add before the `return`:

```python
        # Average leverage over in-market days (only meaningful for a
        # variable-exposure sleeve). NaN when there is no leverage column.
        avg_leverage = float("nan")
        if 'target_leverage' in df.columns:
            lev = df['target_leverage'].values.astype(float)
            in_mkt_lev = lev[lev > 0]
            avg_leverage = float(in_mkt_lev.mean()) if in_mkt_lev.size else 0.0
```

and add `"avg_leverage": avg_leverage` to the returned dict.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_vol_target_leverage.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all green (previous total + 2 new).

- [ ] **Step 6: Commit**

```bash
git add backtest/strat_backtest.py tests/test_vol_target_leverage.py
git commit -m "feat(engine): report avg in-market leverage in trade stats"
```

---

### Task 2: `VolTargetLeverage` strategy

Subclass `SMATrendFollowing`; keep its `in_market`; override leverage with a pure vol-target sizing method.

**Files:**
- Modify: `backtest/strat_backtest.py` (add class after `SMATrendFollowing`, before `DualSignalAgreement`)
- Test: `tests/test_vol_target_leverage.py` (extend)

**Interfaces:**
- Consumes: `SMATrendFollowing` (base), its `_add_indicator_logic` (sets `df['in_market']`, recomputes `df['SMA']`).
- Produces:
  - `class VolTargetLeverage(SMATrendFollowing)` with `__init__(self, target_vol=0.45, l_min=1.0, l_max=3.0, vol_window=20, sma_window=200, atr_multiplier=2.5)`.
  - A pure static method `VolTargetLeverage._size_leverage(close, in_market, target_vol, l_min, l_max, vol_window) -> np.ndarray` returning per-day `target_leverage` (0 where out-of-market or vol undefined).
  - `generate_signals` yields `df['target_leverage']` (float) and `df['in_market'] = df['target_leverage'] > 0`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vol_target_leverage.py`:

```python
from backtest.strat_backtest import VolTargetLeverage


def _vol_frame(daily_moves):
    """Build a Close series from a list of daily returns (Close[0]=100)."""
    closes = [100.0]
    for r in daily_moves:
        closes.append(closes[-1] * (1 + r))
    idx = pd.date_range("2000-01-01", periods=len(closes), freq="D")
    return pd.Series(closes, index=idx)


def test_size_leverage_hits_l_max_in_calm_regime():
    # Very low, steady vol while in-market -> target_vol/realized_vol is large
    # -> clamped to l_max.
    close = _vol_frame([0.0005] * 40)          # ~tiny daily moves
    in_market = pd.Series(True, index=close.index)
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=4.0, vol_window=20)
    # After warm-up (>=vol_window+1 days), leverage should sit at the cap.
    assert lev[-1] == 4.0


def test_size_leverage_hits_l_min_in_high_vol_regime():
    # Large alternating daily moves -> high realized vol -> ratio < 1 ->
    # clamped up to l_min.
    close = _vol_frame([0.06, -0.06] * 20)
    in_market = pd.Series(True, index=close.index)
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=4.0, vol_window=20)
    assert lev[-1] == 1.0


def test_size_leverage_is_zero_out_of_market():
    close = _vol_frame([0.0005] * 40)
    in_market = pd.Series(False, index=close.index)   # never in market
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=4.0, vol_window=20)
    assert np.all(lev == 0.0)


def test_size_leverage_is_lookahead_free():
    # A single huge move at index t must not change leverage until t+1
    # (realized vol is shifted one day).
    moves = [0.001] * 30
    moves[25] = 0.15                       # vol spike on day 26 (index 26 in close)
    close = _vol_frame(moves)
    in_market = pd.Series(True, index=close.index)
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=5.0, vol_window=20)
    # The spike is the return into close index 26; shifted vol means leverage
    # at index 26 is still the pre-spike (high) level, and index 27 drops.
    assert lev[26] > lev[27]


def test_strategy_wires_both_columns_on_uptrend():
    # 260-day steady uptrend so SMA200 is valid and price sits above the band.
    n = 260
    idx = pd.date_range("2000-01-01", periods=n, freq="D")
    close = pd.Series(100.0 * (1.001 ** np.arange(n)), index=idx)
    df = pd.DataFrame({
        "Close": close.values,
        "ATR": np.full(n, 0.5),
        "Daily_Return_1x": close.pct_change().fillna(0).values,
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }, index=idx)
    strat = VolTargetLeverage(l_max=4.0)
    out, _ = strat.generate_signals(df.copy())
    assert "target_leverage" in out.columns
    assert (out["in_market"] == (out["target_leverage"] > 0)).all()
    # Warm-up (first vol_window days) is cash; later in-market days are levered.
    assert out["target_leverage"].iloc[:5].eq(0.0).all()
    assert out["target_leverage"].iloc[-1] > 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_vol_target_leverage.py -q`
Expected: FAIL with `ImportError: cannot import name 'VolTargetLeverage'`.

- [ ] **Step 3: Implement the class**

Add to `backtest/strat_backtest.py` after `SMATrendFollowing` (before `DualSignalAgreement`):

```python
class VolTargetLeverage(SMATrendFollowing):
    """Vol-targeted leverage on top of the binary SMA+ATR trend rule. Keeps
    SMATrendFollowing's entry/exit (in_market) EXACTLY and only replaces the
    fixed leverage with target-vol sizing while in-market:

        L_t = clamp(target_vol / realized_vol_t, l_min, l_max)

    where realized_vol_t is the trailing vol_window-day annualized vol of the
    underlying, shifted one day so today's leverage uses only data through
    yesterday. Out of market -> 0x (the hard crash exit is unchanged). The
    idea: allow >3x in unusually calm strong uptrends (l_max>3), the one
    leverage direction the cash-rotating trend rule does not already cover."""

    def __init__(self, target_vol=0.45, l_min=1.0, l_max=3.0, vol_window=20,
                 sma_window=200, atr_multiplier=2.5):
        super().__init__(sma_window=sma_window, atr_multiplier=atr_multiplier)
        self.name = (f"Vol-Target Leverage (tgt {target_vol:.0%}, "
                     f"{l_min}-{l_max}x, {vol_window}d vol)")
        self.target_vol = target_vol
        self.l_min = l_min
        self.l_max = l_max
        self.vol_window = vol_window

    @staticmethod
    def _size_leverage(close, in_market, target_vol, l_min, l_max, vol_window):
        """Pure vol-target sizing -> per-day target_leverage array. Lookahead-
        free: realized vol is shifted one day. 0 where out of market or where
        vol is undefined (warm-up)."""
        realized_vol = close.pct_change().rolling(vol_window).std() * np.sqrt(252)
        realized_vol = realized_vol.shift(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            target = (target_vol / realized_vol).clip(lower=l_min, upper=l_max)
        invested = in_market.to_numpy(dtype=bool) & realized_vol.notna().to_numpy()
        lev = np.where(invested, target.to_numpy(), 0.0)
        return np.nan_to_num(lev, nan=0.0)

    def _add_indicator_logic(self, df):
        df = super()._add_indicator_logic(df)   # sets df['in_market'] (shifted)
        df['target_leverage'] = self._size_leverage(
            df['Close'], df['in_market'], self.target_vol,
            self.l_min, self.l_max, self.vol_window)
        df['in_market'] = df['target_leverage'] > 0
        return df
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_vol_target_leverage.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backtest/strat_backtest.py tests/test_vol_target_leverage.py
git commit -m "feat(strategy): VolTargetLeverage vol-targeted leverage sleeve"
```

---

### Task 3: Screen script + KPI table

Run the 1990–2026 vol-target sweep vs baselines; add avg-leverage and rebalances columns.

**Files:**
- Create: `backtest/vol_target_screen.py`
- Create (output): `backtest/vol_target_screen_output.md` (generated)

**Interfaces:**
- Consumes: `Backtester`, `SMATrendFollowing`, `VolTargetLeverage` from `backtest.strat_backtest`; `calmar`, `sharpe_from_equity` from `backtest.dynamic_leverage_screen`; `avg_leverage`/`rebalances` from the results dict.
- Produces: `python backtest/vol_target_screen.py` writes/pri­nts the KPI table.

- [ ] **Step 1: Implement the screen script**

Create `backtest/vol_target_screen.py`:

```python
"""Single-path screen for vol-targeted leverage (up-scaling).

Runs 1990-2026 on the single-signal ^NDX sleeve, pre-tax, frictionless,
comparing three L_max caps (3x/4x/5x) of a target-vol leverage rule against
binary-3x and fixed-2x. GO/NO-GO screen, NOT a headline: vol-targeting
rebalances daily, so a frictionless result is a SOFT UPPER BOUND. A real
result requires the friction-aware confirm stage (not in this script).

Run:
    python backtest/vol_target_screen.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester, SMATrendFollowing, VolTargetLeverage
from backtest.dynamic_leverage_screen import calmar, sharpe_from_equity

OUTPUT_PATH = REPO_ROOT / "backtest" / "vol_target_screen_output.md"
START = "1990-01-01"
YEARS = 36
L_MAX_SWEEP = [3.0, 4.0, 5.0]
TARGET_VOL = 0.45


def _kpis(res):
    eq = res["equity_curve"]
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    max_dd = res["max_drawdown"] / 100.0
    return {
        "cagr": cagr, "max_dd": max_dd,
        "calmar": calmar(cagr, max_dd), "sharpe": sharpe_from_equity(eq),
        "avg_lev": res.get("avg_leverage", float("nan")),
        "trades": res.get("total_trades", 0),
        "rebalances": res.get("rebalances", 0),
    }


def _run(strategy, leverage):
    env = Backtester(base_ticker="^NDX", signal_ticker="^NDX",
                     start_date=START, period_years=YEARS, leverage=leverage,
                     expense_ratio=0.0095, initial_fund=10000, verbose=False)
    res = env.run(strategy)
    return _kpis(res) if res else None


def run_suite():
    rows = [
        ("Binary 3x (baseline)", _run(SMATrendFollowing(atr_multiplier=2.5), 3)),
        ("Fixed 2x (same signal)", _run(SMATrendFollowing(atr_multiplier=2.5), 2)),
    ]
    for lmax in L_MAX_SWEEP:
        rows.append((f"VolTarget (cap {lmax:.0f}x)",
                     _run(VolTargetLeverage(target_vol=TARGET_VOL, l_min=1.0,
                                            l_max=lmax), 3)))
    return rows


def format_table(rows):
    head = ("| Strategy | CAGR | Worst DD | Calmar | Sharpe | Avg Lev | Trades | Rebal |\n"
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    body = ""
    for name, k in rows:
        if k is None:
            body += f"| {name} | — | — | — | — | — | — | — |\n"
            continue
        avg = "—" if k["avg_lev"] != k["avg_lev"] else f"{k['avg_lev']:.2f}x"
        body += (f"| {name} | {k['cagr']*100:.2f}% | {k['max_dd']*100:.2f}% | "
                 f"{k['calmar']:.2f} | {k['sharpe']:.2f} | {avg} | {k['trades']} | "
                 f"{k['rebalances']} |\n")
    return head + body


def main():
    rows = run_suite()
    table = format_table(rows)
    note = ("\n> **Screen only, SOFT UPPER BOUND** — single continuous 1990–2026 path, "
            "single-signal ^NDX sleeve, pre-tax, frictionless. Vol-targeting rebalances "
            "daily; a frictionless result flatters it. A go/no-go, not a headline. A real "
            f"result requires the friction-aware confirm stage. target_vol={TARGET_VOL:.0%}, "
            "fixed/untuned.\n")
    doc = f"# Vol-Targeted Leverage — Screen (1990–2026)\n\n{table}{note}"
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(doc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check imports with a quick collection run**

Run: `python -c "import backtest.vol_target_screen as s; print(s.L_MAX_SWEEP, s.TARGET_VOL)"`
Expected: prints `[3.0, 4.0, 5.0] 0.45` with no import error.

- [ ] **Step 3: Run the screen (requires cached ^NDX data)**

Run: `python backtest/vol_target_screen.py`
Expected: prints a 5-row KPI table and writes `backtest/vol_target_screen_output.md`. If data is unavailable, note the exact error, do NOT fabricate numbers, commit the script without an output file, and report DONE_WITH_CONCERNS.

- [ ] **Step 4: Commit**

```bash
git add backtest/vol_target_screen.py backtest/vol_target_screen_output.md
git commit -m "feat(screen): vol-targeted leverage 1990-2026 screen + KPI table"
```

---

### Task 4: Interpret + document the screen result

**Files:**
- Modify: `docs/research-retrospective-2026-08.md` (extend §7 or add §8) if negative/inconclusive
- OR Create: `docs/strategies/vol-target-leverage.md` + README row if a cap beats both baselines

**Interfaces:**
- Consumes: `backtest/vol_target_screen_output.md` (Task 3 output).
- Produces: a committed finding. No code.

- [ ] **Step 1: Read the output and classify**

Read `backtest/vol_target_screen_output.md`. **Win** = a VolTarget row whose Calmar AND Sharpe both materially exceed BOTH baselines. Otherwise **negative/inconclusive**. Note especially whether raising the cap 3→4→5 improves risk-adjusted metrics or merely shifts CAGR/DD together (a slide along the risk/return line), and how high `avg_lev` and `rebalances` ran.

- [ ] **Step 2: Write the finding**

- If **negative/inconclusive:** extend the retrospective's dynamic-leverage section with a short "vol-targeted / up-scaling" subsection: the table verbatim, the honest verdict (whether allowing >3× beat fixed 2×), and the reminder that the confirm stage (friction-aware) was NOT run because the screen didn't clear the bar. Emphasize the daily-rebalancing soft-upper-bound caveat. Link the output + script.
- If **win:** create `docs/strategies/vol-target-leverage.md` (mechanics, table, the soft-upper-bound + >3×-tradeability caveats, confirm-stage still pending) and a README row. Do NOT claim adoption.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: record vol-targeted leverage screen finding"
```

---

## Self-Review

**Spec coverage:** §2 rule → Task 2; §2 sweep {3,4,5} → Task 3 `L_MAX_SWEEP`; §3 no-engine-change-but-avg_leverage → Task 1; §4 baselines + Calmar-AND-Sharpe bar → Task 3 (both baselines), Task 4 (decision rule); §5 metrics (avg lev, rebalances) → Tasks 1, 3; §6 staged + soft-upper-bound framing → Task 3 note, Task 4; §7 caveats → Task 3 note, Task 4; §9 deliverables → Tasks 1–4.

**Placeholder scan:** none; every code step has complete code.

**Type consistency:** `VolTargetLeverage(target_vol, l_min, l_max, vol_window, sma_window, atr_multiplier)`; `_size_leverage(close, in_market, target_vol, l_min, l_max, vol_window) -> ndarray`; `avg_leverage` float key (NaN sentinel); screen `_kpis` reads `avg_leverage`/`rebalances`/`total_trades`/`max_drawdown`/`equity_curve` — consistent across tasks.

**Known follow-up (out of scope, gated on Task 4):** friction-aware + rolling confirm; target_vol/vol_window sensitivity. Built only if a cap wins the screen.
