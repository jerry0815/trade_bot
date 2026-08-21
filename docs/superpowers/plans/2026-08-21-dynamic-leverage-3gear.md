# Dynamic-Leverage 3-Gear Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-day variable-leverage capability to the backtest engine and a single-signal 3-gear trend strategy, then produce a 1990–2026 screen comparing it against the binary-3× and fixed-2× baselines.

**Architecture:** Generalize `Backtester._run_portfolio_math`'s scalar `leverage` into a per-day exposure vector read from an optional `target_leverage` column, adding exactly one new day-type (gear-change) while preserving the existing entry/hold/exit math bit-for-bit. A new `DynamicLeverageTrend` strategy maps a single index's SMA200+ATR band to `{3×, middle-gear, 0×}`. A screen script runs the sweep and prints a KPI table. This plan delivers the **screen stage only** (spec §6); the dual-signal + trailing-stop *confirm* stage and rolling/reconstruction run are a gated follow-up, built only if the screen shows a real edge.

**Tech Stack:** Python, NumPy, pandas, pytest. No new dependencies. Network-free tests (synthetic frames driving `_run_portfolio_math` directly), matching the existing `tests/` style.

## Global Constraints

- **No lookahead:** `target_leverage[t]` must depend only on data through `t−1`. The strategy shifts its signal by 1 (mirrors existing `raw_signal.shift(1)`).
- **Exact backward-compatibility:** when no `target_leverage` column is present, the engine must reproduce current scalar-leverage results bit-for-bit. This is a required regression test.
- **Leverage values** are drawn from the exact set `{0.0, 1.0, 1.5, 2.0, 3.0}`; the engine compares `old_L == new_L` by float equality, which is safe because these values are assigned (never arithmetically derived) and `shift` preserves them exactly.
- **Screen is pre-tax, single continuous path, 1990–2026, single-signal ^NDX sleeve.** Screen results are a go/no-go, never a headline (spec §6).
- **Success bar:** a risk-adjusted win (Calmar and/or Sharpe) above *both* the binary-3× baseline and fixed-2× TQQQ (spec §5). A negative screen across all three middle gears is a valid, documented outcome.
- **Repo conventions:** work on branch `dynamic-leverage-3gear`. Do not modify `bot.py` or the production recommendation. Do not put any model identifier in commits. Keep the repo's `Co-Authored-By` trailer on commits.

---

### Task 1: Engine — per-day exposure vector

Generalize the daily-return construction in `_run_portfolio_math` to consume a per-day leverage array, adding the gear-change day-type. This is the load-bearing change; every downstream task depends on it.

**Files:**
- Modify: `backtest/strat_backtest.py` (`Backtester._run_portfolio_math`, ~lines 960–991)
- Test: `tests/test_dynamic_leverage.py` (create)

**Interfaces:**
- Consumes: an optional `target_leverage` float column on the input `df` (0 ≤ L ≤ 3). Absent → fall back to `self.leverage` gated by `df['in_market']`.
- Produces: unchanged `_run_portfolio_math` return dict (`final_value`, `max_drawdown`, `strategy_twr`, `equity_curve`, etc.). Behavior is now driven by `target_leverage` when present.

- [ ] **Step 1: Write the backward-compat + constant-vector failing tests**

Add to `tests/test_dynamic_leverage.py`:

```python
"""Unit tests for per-day variable leverage in the portfolio math engine.

Network-free: builds synthetic price frames and drives
Backtester._run_portfolio_math directly.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester


def _frame(start, in_market, ret=0.0, o2c=0.0, ovn=0.0, br=0.0, target_leverage=None):
    """Synthetic daily frame. Scalar return args are broadcast to every row."""
    idx = pd.date_range(start, periods=len(in_market), freq="D")
    n = len(idx)
    data = {
        "in_market": np.asarray(in_market, dtype=bool),
        "BR": np.full(n, br, dtype=float),
        "Daily_Return_1x": np.full(n, ret, dtype=float),
        "Open2Close": np.full(n, o2c, dtype=float),
        "Overnight_Return": np.full(n, ovn, dtype=float),
    }
    if target_leverage is not None:
        data["target_leverage"] = np.asarray(target_leverage, dtype=float)
    return pd.DataFrame(data, index=idx)


def test_no_target_leverage_column_matches_scalar():
    # A frame WITHOUT target_leverage must reproduce the scalar-leverage path.
    mask = [True] * 10
    df = _frame("2000-01-01", mask, ret=0.01, o2c=0.008, ovn=0.002, br=0.05)
    env = Backtester(leverage=3, expense_ratio=0.0095, verbose=False)
    baseline = env._run_portfolio_math(df.copy())["final_value"]

    # Same frame WITH an explicit constant 3x vector must match exactly.
    df2 = df.copy()
    df2["target_leverage"] = 3.0
    got = env._run_portfolio_math(df2)["final_value"]
    assert got == baseline


def test_constant_2x_vector_matches_scalar_2x():
    mask = [True] * 10
    df = _frame("2000-01-01", mask, ret=0.01, o2c=0.008, ovn=0.002, br=0.05)
    env3 = Backtester(leverage=2, expense_ratio=0.0095, verbose=False)
    scalar_2x = env3._run_portfolio_math(df.copy())["final_value"]

    df2 = df.copy()
    df2["target_leverage"] = 2.0
    env_any = Backtester(leverage=3, expense_ratio=0.0095, verbose=False)  # scalar ignored
    got = env_any._run_portfolio_math(df2)["final_value"]
    assert abs(got - scalar_2x) < 1e-9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: FAIL — `test_constant_2x_vector_matches_scalar_2x` fails because the engine currently ignores `target_leverage` (uses `self.leverage`), so the 2x vector under an env with `leverage=3` returns the 3x result.

- [ ] **Step 3: Implement the per-day exposure vector**

In `_run_portfolio_math`, the current block (~lines 971–991) computes `entering_mask`/`exiting_mask` from `in_mkt` and builds `daily_ret_arr` at the scalar `self.leverage`. Replace the transition-mask block **and** the daily-return block with:

```python
        # --- Per-day target leverage ---
        # A strategy may emit a `target_leverage` column (0..3) for a variable-
        # exposure sleeve. Absent, fall back to the scalar `self.leverage` gated
        # by in_market — bit-for-bit identical to the pre-vector behavior.
        if 'target_leverage' in df.columns:
            new_L = np.nan_to_num(df['target_leverage'].values.astype(float))
        else:
            new_L = np.where(in_mkt, float(self.leverage), 0.0)
        old_L      = np.empty(n, dtype=float)
        old_L[0]   = 0.0
        old_L[1:]  = new_L[:-1]

        in_now  = new_L > 0
        in_prev = old_L > 0
        entering_mask = in_now & ~in_prev                    # cash -> position
        exiting_mask  = ~in_now & in_prev                    # position -> cash
        gear_change   = in_now & in_prev & (new_L != old_L)  # rebalance, stay invested

        # --- Pre-compute the full daily_return array in one vectorised pass ---
        drag_new = (((new_L - 1) * br_arr) + self.expense_ratio) / 252
        drag_old = (((old_L - 1) * br_arr) + self.expense_ratio) / 252
        cash_ret = (br_arr * 0.8) / 252

        # Hold default: leveraged close-to-close when in market, cash when out.
        daily_ret_arr = np.where(in_now, ret_arr * new_L - drag_new, cash_ret)
        # Entry days: entered at open, only earn open->close at the new exposure.
        daily_ret_arr[entering_mask] = (o2c_arr[entering_mask] * new_L[entering_mask]
                                        - drag_new[entering_mask])
        # Exit days: sold at open, only the overnight gap at the OLD exposure.
        daily_ret_arr[exiting_mask]  = (ovn_arr[exiting_mask] * old_L[exiting_mask]
                                        - drag_old[exiting_mask])
        # Gear-change days: overnight gap at old exposure, intraday at new (a
        # next-day-open rebalance). Reduces to entry/exit when one side is 0.
        daily_ret_arr[gear_change]   = (ovn_arr[gear_change] * old_L[gear_change]
                                        + o2c_arr[gear_change] * new_L[gear_change]
                                        - drag_new[gear_change])
```

Delete the now-superseded lines: the old `prev_mkt`/`entering_mask`/`exiting_mask` block (~971–976) and the old `leverage_drag`/`cash_ret`/`daily_ret_arr` block (~978–991). The scalar loop below (`entering_mask[i]`, `exiting_mask[i]`) is unchanged — those masks now mean "enter from cash" / "exit to cash", exactly as before.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Run the FULL existing suite to confirm no regression**

Run: `python -m pytest tests/ -q`
Expected: all previously-passing tests still pass (the fallback path is bit-for-bit identical).

- [ ] **Step 6: Commit**

```bash
git add backtest/strat_backtest.py tests/test_dynamic_leverage.py
git commit -m "feat(engine): per-day variable leverage via target_leverage column"
```

---

### Task 2: Engine — four day-type coverage + no-lookahead assertions

Prove each of the four day-types (hold / entry / exit / gear-change) computes the exact intended daily return, especially the new gear-change row.

**Files:**
- Test: `tests/test_dynamic_leverage.py` (extend)

**Interfaces:**
- Consumes: `Backtester._run_portfolio_math` with a `target_leverage` column (Task 1).
- Produces: nothing new; adds regression coverage relied on by Tasks 3–5.

- [ ] **Step 1: Write the day-type coverage tests**

Append to `tests/test_dynamic_leverage.py`:

```python
def _final_from_daily(returns):
    """Compound a list of daily returns into a growth factor."""
    f = 1.0
    for r in returns:
        f *= (1 + r)
    return f


def test_gear_change_day_uses_overnight_old_intraday_new():
    # Day 0: enter at 3x. Day 1: hold 3x. Day 2: gear-change 3x -> 1.5x.
    # BR=0 so drag=0 and cash_ret=0; isolates the return formula.
    lev = [3.0, 3.0, 1.5]
    df = _frame("2000-01-01", [True, True, True],
                ret=0.010, o2c=0.006, ovn=0.004, br=0.0, target_leverage=lev)
    env = Backtester(leverage=3, expense_ratio=0.0, verbose=False)
    res = env._run_portfolio_math(df)

    # Day0 entry: o2c*3 ; Day1 hold: ret*3 ; Day2 gear-change: ovn*3 + o2c*1.5
    expected = _final_from_daily([
        0.006 * 3.0,
        0.010 * 3.0,
        0.004 * 3.0 + 0.006 * 1.5,
    ])
    assert abs(res["final_value"] / 10000 - expected) < 1e-9


def test_exit_day_uses_overnight_at_old_leverage():
    # Day 0: enter 2x. Day 1: hold 2x. Day 2: exit to cash.
    lev = [2.0, 2.0, 0.0]
    df = _frame("2000-01-01", [True, True, False],
                ret=0.010, o2c=0.006, ovn=0.004, br=0.0, target_leverage=lev)
    env = Backtester(leverage=2, expense_ratio=0.0, verbose=False)
    res = env._run_portfolio_math(df)

    expected = _final_from_daily([
        0.006 * 2.0,   # entry: open->close at 2x
        0.010 * 2.0,   # hold
        0.004 * 2.0,   # exit: overnight gap at the OLD (2x) exposure
    ])
    assert abs(res["final_value"] / 10000 - expected) < 1e-9


def test_cash_day_earns_money_market_only():
    # Never in market: every day earns BR*0.8/252, at no leverage.
    lev = [0.0, 0.0, 0.0]
    df = _frame("2000-01-01", [False, False, False],
                ret=0.05, o2c=0.05, ovn=0.05, br=0.05, target_leverage=lev)
    env = Backtester(leverage=3, expense_ratio=0.0095, verbose=False)
    res = env._run_portfolio_math(df)

    daily_cash = 0.05 * 0.8 / 252
    expected = _final_from_daily([daily_cash] * 3)
    assert abs(res["final_value"] / 10000 - expected) < 1e-9
```

- [ ] **Step 2: Run to verify they pass**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: PASS (Task 1's implementation already satisfies these; they lock the exact formulas).

- [ ] **Step 3: Commit**

```bash
git add tests/test_dynamic_leverage.py
git commit -m "test(engine): lock the four variable-leverage day-type formulas"
```

---

### Task 3: `DynamicLeverageTrend` strategy (single-signal 3-gear)

Map a single index's SMA200+ATR band to `{3×, middle-gear, 0×}`, shifted by one day for next-day-open execution.

**Files:**
- Modify: `backtest/strat_backtest.py` (add class after `DualSignalAgreement`, before `VolatilityFilter`)
- Test: `tests/test_dynamic_leverage.py` (extend)

**Interfaces:**
- Consumes: `BaseStrategy` (base class), `get_cached_signals(ticker, sma_window)` (existing helper returning a frame with `Close`, `SMA`, `ATR`).
- Produces: `class DynamicLeverageTrend(BaseStrategy)` with `__init__(self, middle_gear, sma_window=200, atr_multiplier=2.5, signal_ticker="^NDX")`. Its `generate_signals(df)` sets `df['target_leverage']` (float in `{0.0, middle_gear, 3.0}`) and `df['in_market'] = df['target_leverage'] > 0`.

- [ ] **Step 1: Write the strategy mapping + no-lookahead tests**

These drive `_add_indicator_logic` on a hand-built band frame. Append to `tests/test_dynamic_leverage.py`:

```python
from backtest.strat_backtest import DynamicLeverageTrend


def _band_frame(closes, sma=100.0, atr=10.0, mult=2.5):
    """Frame where Close crosses a fixed SMA+/-mult*ATR band.

    Upper = sma + mult*atr, Lower = sma - mult*atr. Above upper -> bull (3x),
    below lower -> bear (cash), between -> transition (middle gear).
    """
    idx = pd.date_range("2000-01-01", periods=len(closes), freq="D")
    n = len(idx)
    return pd.DataFrame({
        "Close": np.asarray(closes, dtype=float),
        "SMA": np.full(n, sma),
        "ATR": np.full(n, atr),
        "Daily_Return_1x": np.zeros(n),
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }, index=idx)


def test_three_states_map_to_three_gears():
    # Upper=125, Lower=75. Closes chosen to sit clearly bull / mid / bear.
    strat = DynamicLeverageTrend(middle_gear=1.5)
    closes = [130, 130, 100, 100, 60, 60]   # bull, bull, mid, mid, bear, bear
    df = _band_frame(closes)
    out, _ = strat.generate_signals(df.copy())

    # target_leverage is the state shifted by 1 day (next-day-open execution),
    # so assert on the post-shift alignment: state[t] acts at t+1.
    tl = out["target_leverage"].tolist()
    # Day0 seeds the initial state; the mapping shows from day 1 onward.
    assert tl[1] == 3.0     # yesterday bull  -> 3x today
    assert tl[3] == 1.5     # yesterday mid   -> middle gear today
    assert tl[5] == 0.0     # yesterday bear  -> cash today
    assert (out["in_market"] == (out["target_leverage"] > 0)).all()


def test_target_leverage_is_lookahead_free():
    # A single bull day surrounded by mid days must not raise today's leverage
    # until the day AFTER the bull close (signal shifted by 1).
    strat = DynamicLeverageTrend(middle_gear=1.0)
    closes = [100, 130, 100]   # mid, bull, mid
    df = _band_frame(closes)
    out, _ = strat.generate_signals(df.copy())
    tl = out["target_leverage"].tolist()
    # The bull close is day 1; its 3x exposure may only appear on day 2.
    assert tl[1] != 3.0
    assert tl[2] == 3.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: FAIL with `ImportError: cannot import name 'DynamicLeverageTrend'`.

- [ ] **Step 3: Implement the strategy class**

Add to `backtest/strat_backtest.py` after `DualSignalAgreement`:

```python
class DynamicLeverageTrend(BaseStrategy):
    """Single-signal 3-gear leverage: one index's SMA+ATR band maps to
    {3x above the upper band, `middle_gear` inside the band, 0x below the
    lower band}. Unlike the binary rule, the neutral band is a defined
    reduced-exposure sleeve rather than a 'hold prior position' state.
    Signal is shifted one day for next-day-open execution (lookahead-free)."""

    def __init__(self, middle_gear, sma_window=200, atr_multiplier=2.5,
                 signal_ticker="^NDX"):
        super().__init__(name=f"Dynamic-Leverage 3-Gear (mid {middle_gear}x, "
                              f"ATR x{atr_multiplier})")
        self.middle_gear = float(middle_gear)
        self.sma_window = sma_window
        self.atr_multiplier = atr_multiplier
        self.signal_ticker = signal_ticker

    def _add_indicator_logic(self, df):
        df = df.copy()
        upper = df['SMA'] + df['ATR'] * self.atr_multiplier
        lower = df['SMA'] - df['ATR'] * self.atr_multiplier
        bull = df['Close'] > upper
        bear = df['Close'] < lower

        # State BEFORE the execution shift: 3x bull, middle in-band, 0 bear.
        state = np.where(bull, 3.0, np.where(bear, 0.0, self.middle_gear))
        state = pd.Series(state, index=df.index)

        # Seed initial exposure from the first day's own state, then shift 1
        # day so today's exposure is decided by yesterday's close.
        initial = float(state.iloc[0])
        df['target_leverage'] = state.shift(1).fillna(initial).astype(float)
        df['in_market'] = df['target_leverage'] > 0
        return df
```

Note: `generate_signals` (on `BaseStrategy`) calls `_add_indicator_logic` and validates the `in_market` column exists. Confirm `BaseStrategy.generate_signals` invokes `_add_indicator_logic`; if the base instead requires a differently-named hook, match the pattern used by `SMATrendFollowing`/`DualSignalAgreement` (they define `_add_indicator_logic`).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: PASS (all strategy tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backtest/strat_backtest.py tests/test_dynamic_leverage.py
git commit -m "feat(strategy): single-signal 3-gear DynamicLeverageTrend"
```

---

### Task 4: Rebalance count in trade stats

Surface gear changes as a separate "rebalances" metric so the middle gear's added turnover is honestly costed, not hidden inside the trade count.

**Files:**
- Modify: `backtest/strat_backtest.py` (`Backtester._calculate_trade_stats`, ~lines 916–933)
- Test: `tests/test_dynamic_leverage.py` (extend)

**Interfaces:**
- Consumes: input `df`, optionally carrying a `target_leverage` column.
- Produces: the trade-stats dict gains a `"rebalances"` int key (0 when no `target_leverage` column). `total_trades` still counts entries from cash only.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dynamic_leverage.py`:

```python
def test_rebalances_counts_gear_changes_not_entries():
    # Path: cash -> 3x (entry) -> 3x -> 1.5x (rebalance) -> 1.5x -> 0 (exit).
    lev = [0.0, 3.0, 3.0, 1.5, 1.5, 0.0]
    df = _frame("2000-01-01", [x > 0 for x in lev],
                target_leverage=lev)
    env = Backtester(verbose=False)
    stats = env._calculate_trade_stats(df)
    assert stats["total_trades"] == 1     # one entry from cash
    assert stats["rebalances"] == 1       # the 3x -> 1.5x change


def test_rebalances_zero_without_target_leverage():
    df = _frame("2000-01-01", [True, True, False, True])
    env = Backtester(verbose=False)
    stats = env._calculate_trade_stats(df)
    assert stats["rebalances"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_dynamic_leverage.py -k rebalance -q`
Expected: FAIL with `KeyError: 'rebalances'`.

- [ ] **Step 3: Implement**

In `_calculate_trade_stats`, before the `return`, add:

```python
        # Rebalances: days the position changes leverage without going to cash
        # (only meaningful for a variable-exposure sleeve).
        rebalances = 0
        if 'target_leverage' in df.columns:
            lev = df['target_leverage'].values.astype(float)
            prev = np.empty(len(lev)); prev[0] = 0.0; prev[1:] = lev[:-1]
            rebalances = int(np.sum((lev > 0) & (prev > 0) & (lev != prev)))
```

and add `"rebalances": rebalances` to the returned dict.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/strat_backtest.py tests/test_dynamic_leverage.py
git commit -m "feat(engine): report gear-change rebalances in trade stats"
```

---

### Task 5: Screen script + KPI table

Run the 1990–2026 single-path screen: three middle gears vs the two baselines, on the single-signal ^NDX sleeve, pre-tax. Print a table with CAGR, worst DD, Calmar, Sharpe, trades, rebalances.

**Files:**
- Create: `backtest/dynamic_leverage_screen.py`
- Create (output): `backtest/dynamic_leverage_screen_output.md` (generated)

**Interfaces:**
- Consumes: `Backtester`, `SMATrendFollowing`, `DynamicLeverageTrend` from `backtest.strat_backtest`; `equity_curve` and `max_drawdown` from the results dict.
- Produces: a runnable script (`python backtest/dynamic_leverage_screen.py`) that writes the KPI table to `backtest/dynamic_leverage_screen_output.md` and prints it.

- [ ] **Step 1: Write the Sharpe/Calmar helper with a unit test**

Append to `tests/test_dynamic_leverage.py`:

```python
from backtest.dynamic_leverage_screen import sharpe_from_equity, calmar


def test_calmar_is_cagr_over_maxdd():
    assert abs(calmar(0.20, -0.50) - 0.40) < 1e-9    # 20% / 50%
    assert calmar(0.20, 0.0) == float("inf")          # no drawdown guard


def test_sharpe_of_constant_growth_is_large_and_finite():
    # A perfectly smooth up-curve has ~zero return vol -> very high Sharpe.
    idx = pd.date_range("2000-01-01", periods=300, freq="B")
    eq = pd.Series(10000 * (1.0002 ** np.arange(300)), index=idx)
    s = sharpe_from_equity(eq)
    assert np.isfinite(s) and s > 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_dynamic_leverage.py -k "calmar or sharpe" -q`
Expected: FAIL with `ModuleNotFoundError`/`ImportError` for `dynamic_leverage_screen`.

- [ ] **Step 3: Implement the screen script**

Create `backtest/dynamic_leverage_screen.py`:

```python
"""Single-path screen (spec §6) for the dynamic-leverage 3-gear idea.

Runs 1990-2026 on the single-signal ^NDX sleeve, pre-tax, comparing three
middle gears against the binary-3x baseline and fixed-2x TQQQ. This is a
GO/NO-GO screen, not a headline: single path, frictionless. A real result
requires the rolling + reconstruction confirm stage (not in this script).

Run:
    python backtest/dynamic_leverage_screen.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    Backtester, SMATrendFollowing, DynamicLeverageTrend,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "dynamic_leverage_screen_output.md"
START = "1990-01-01"
YEARS = 36
MIDDLE_GEARS = [1.0, 1.5, 2.0]


def calmar(cagr, max_dd):
    """CAGR / |MaxDD|. max_dd is a fraction <= 0; 0 drawdown -> inf."""
    if max_dd == 0:
        return float("inf")
    return cagr / abs(max_dd)


def sharpe_from_equity(equity, rf=0.0):
    """Annualised Sharpe from a daily equity curve (252-day convention)."""
    daily = equity.pct_change().dropna()
    if daily.std() == 0:
        return float("inf")
    return float((daily.mean() - rf / 252) / daily.std() * np.sqrt(252))


def _kpis(res):
    eq = res["equity_curve"]
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    max_dd = res["max_drawdown"] / 100.0
    return {
        "cagr": cagr,
        "max_dd": max_dd,
        "calmar": calmar(cagr, max_dd),
        "sharpe": sharpe_from_equity(eq),
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
    rows = []
    # Baseline 1: binary 3x-or-cash (single-signal trend).
    rows.append(("Binary 3x (baseline)",
                 _run(SMATrendFollowing(atr_multiplier=2.5), leverage=3)))
    # Baseline 2: fixed 2x, same signal.
    rows.append(("Fixed 2x (same signal)",
                 _run(SMATrendFollowing(atr_multiplier=2.5), leverage=2)))
    # Candidates: 3-gear with each middle gear. Engine leverage is ignored
    # because the strategy emits target_leverage; pass 3 for clarity.
    for mg in MIDDLE_GEARS:
        rows.append((f"3-Gear (mid {mg}x)",
                     _run(DynamicLeverageTrend(middle_gear=mg,
                                               signal_ticker="^NDX"), leverage=3)))
    return rows


def format_table(rows):
    head = ("| Strategy | CAGR | Worst DD | Calmar | Sharpe | Trades | Rebal |\n"
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    body = ""
    for name, k in rows:
        if k is None:
            body += f"| {name} | — | — | — | — | — | — |\n"
            continue
        body += (f"| {name} | {k['cagr']*100:.2f}% | {k['max_dd']*100:.2f}% | "
                 f"{k['calmar']:.2f} | {k['sharpe']:.2f} | {k['trades']} | "
                 f"{k['rebalances']} |\n")
    return head + body


def main():
    rows = run_suite()
    table = format_table(rows)
    note = ("\n> **Screen only** — single continuous 1990–2026 path, single-signal "
            "^NDX sleeve, pre-tax, frictionless. A go/no-go, not a headline. "
            "A real result requires the rolling + reconstruction confirm stage.\n")
    doc = f"# Dynamic-Leverage 3-Gear — Screen (1990–2026)\n\n{table}{note}"
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(doc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `python -m pytest tests/test_dynamic_leverage.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the screen (requires yfinance data / cached signals)**

Run: `python backtest/dynamic_leverage_screen.py`
Expected: prints a 5-row KPI table and writes `backtest/dynamic_leverage_screen_output.md`. If network/data is unavailable, note it and defer running to an environment with data — the code is still committed and unit-tested.

- [ ] **Step 6: Commit**

```bash
git add backtest/dynamic_leverage_screen.py tests/test_dynamic_leverage.py backtest/dynamic_leverage_screen_output.md
git commit -m "feat(screen): dynamic-leverage 3-gear 1990-2026 screen + KPI table"
```

---

### Task 6: Interpret + document the screen result

Turn the screen table into an honest finding: does any middle gear beat *both* baselines on Calmar/Sharpe? Record the outcome where the repo keeps its research trail.

**Files:**
- Modify: `docs/research-retrospective-2026-08.md` (add a "Dynamic-leverage 3-gear" subsection) **if the screen is negative or inconclusive**
- OR Create: `docs/strategies/dynamic-leverage-3gear.md` + a README row **if a gear beats both baselines** and warrants the confirm stage

**Interfaces:**
- Consumes: `backtest/dynamic_leverage_screen_output.md` (Task 5 output).
- Produces: a committed finding doc. No code.

- [ ] **Step 1: Read the screen output and classify the result**

Read `backtest/dynamic_leverage_screen_output.md`. Decision rule (spec §5): a **win** is any 3-gear row whose Calmar *and/or* Sharpe materially exceeds *both* "Binary 3x" and "Fixed 2x". Otherwise it is a **negative/inconclusive** screen.

- [ ] **Step 2: Write the finding**

- If **negative/inconclusive:** add a subsection to `docs/research-retrospective-2026-08.md` summarizing the table, stating that the middle gear did not beat the binary-3× / fixed-2× baselines on a risk-adjusted basis, and that (per the staged plan) the rolling confirm stage was **not** run. Link the screen output. Keep it to a short, honest paragraph plus the table.
- If **win:** create `docs/strategies/dynamic-leverage-3gear.md` with the mechanics, the screen table, the explicit caveat that this is a *screen* pending the rolling + reconstruction confirm, and add a README "Strategy docs" row. Do **not** claim adoption — the confirm stage is a separate, gated follow-up plan.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: record dynamic-leverage 3-gear screen finding"
```

---

## Self-Review

**Spec coverage:**
- §2 rule (states → gears) → Task 3 (single-signal instantiation; dual-signal confirm is the gated follow-up, stated in the plan header).
- §2 middle-gear sweep {1×,1.5×,2×} → Task 5 `MIDDLE_GEARS`.
- §3 per-day exposure vector + four day-types → Tasks 1, 2.
- §3 backward-compat contract → Task 1 Steps 1, 5.
- §4 strategy object (in_market == target_leverage>0; rebalances reported) → Tasks 3, 4.
- §5 beat both baselines on Calmar/Sharpe → Task 5 (both baselines present), Task 6 (decision rule).
- §6 staged validation, single-signal screen first → whole plan scoped to screen; confirm deferred (header + Task 6).
- §7 realism caveats → surfaced in Task 5 script note and Task 6 finding.
- §8 tests (backward-compat, constant-vector, four day-types, no-lookahead, state mapping) → Tasks 1, 2, 3.
- §10 deliverables (engine, strategy, tests, screen script, finding doc) → Tasks 1–6.

**Placeholder scan:** no TBD/TODO; every code step has concrete code; test bodies are complete.

**Type consistency:** `DynamicLeverageTrend(middle_gear, sma_window, atr_multiplier, signal_ticker)`, `target_leverage` float column, `in_market` bool column, `sharpe_from_equity(equity)`, `calmar(cagr, max_dd)`, `rebalances` int key — used identically across Tasks 3–6.

**Known follow-up (out of scope, gated on Task 6):** dual-signal + trailing-stop confirm sleeve, rolling-window + reconstruction run, tax-aware gear-change handling (spec §7). These become a separate plan only if the screen wins.
