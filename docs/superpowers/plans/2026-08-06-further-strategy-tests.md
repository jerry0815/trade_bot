# Further Strategy Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixed-window ("velocity") trailing stop and measure it against the existing peak-based stop, plus produce a QQQ-1x strategy table and a taxable-account (after-tax) table.

**Architecture:** One engine change — a new `BaseStrategy._apply_velocity_stop` method (parallel to the existing `_apply_trailing_stop`, peak-based stop left byte-for-byte untouched as its regression gate) driven by four new mutually-exclusive strategy params. Three new standalone research scripts under `backtest/` follow the existing convention (print a markdown table to stdout **and** write a sibling `_output.md`). README tables and `docs/` finding notes follow.

**Tech Stack:** Python 3, pandas 2.2.3, numpy, pytest 9.1.1. Data via `yfinance` cached through `get_cached_data`/`get_cached_signals` in `backtest/strat_backtest.py`.

## Global Constraints

- **Lookahead-free:** every stop decision for day `i` may read only `close[i-1]` and earlier (the code lags via `np.roll(close, 1)` with `[0]` reset to `close[0]`). Matches `_apply_trailing_stop`.
- **Regression gate:** `_apply_trailing_stop` (peak stop) output must stay byte-for-byte unchanged — do not modify it; add the new method separately.
- **Stops are mutually exclusive per run:** a strategy sets *either* `trailing_stop_pct` (peak) *or* `velocity_stop_pct` (velocity), never both. Wiring uses `if peak … elif velocity …`.
- **Reference price:** velocity stop tracks the unleveraged signal-ticker price (`^GSPC`), via the existing `price=` argument path — same as the peak stop.
- **Stop-name strings use one decimal place** for pct (`:.1f`) to avoid column-key collisions in `RollingBacktester` (per the existing comment at `strat_backtest.py:395`).
- **Research scripts:** print table to stdout AND write `backtest/<name>_output.md`; cross-validate new numbers against already-published README tables where a shared row exists.
- **Rolling methodology:** 26-year windows, monthly step, `$10,000` lump sum, `warmup_aware_start_dates`, next-day-open execution (all already in the engine — reuse, don't reimplement).
- **Velocity stop is backtest-only:** no `bot.py` live-reporting / `_trailing_stop_status` equivalent in this plan (not being promoted to live yet).

---

### Task 1: Velocity stop engine method + params

**Files:**
- Modify: `backtest/strat_backtest.py` — add `_apply_velocity_stop` to `BaseStrategy` (after `_apply_trailing_stop`, ~line 306); add 4 params to `SMATrendFollowing.__init__` (~line 381) and `DualSignalAgreement.__init__` (~line 585); wire into both `_add_indicator_logic` methods (~line 573 and ~line 635).
- Test: `tests/test_velocity_stop.py` (new; `tests/` dir is new).

**Interfaces:**
- Produces: `BaseStrategy._apply_velocity_stop(self, df, price=None) -> pd.Series[bool]`, indexed like `df`. Reads `df['in_market']` (bool, execution-day column) and the reference price (`price` if given else `df['Close']`). Uses instance attrs `velocity_stop_pct: float|None`, `velocity_stop_window: int`, `velocity_stop_mode: str` (`"rolling_max"`|`"point_to_point"`), `velocity_stop_cooldown_days: int`.
- New constructor kwargs on `SMATrendFollowing` and `DualSignalAgreement`: `velocity_stop_pct=None, velocity_stop_window=30, velocity_stop_mode="rolling_max", velocity_stop_cooldown_days=60`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_velocity_stop.py`:

```python
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing


def _run(prices, in_market, pct, window, mode, cooldown):
    strat = SMATrendFollowing(
        velocity_stop_pct=pct, velocity_stop_window=window,
        velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown,
    )
    df = pd.DataFrame({"Close": prices, "in_market": in_market})
    return strat._apply_velocity_stop(df).tolist()


def test_rolling_max_triggers_on_fast_drop_and_cools_down():
    # close[4]=94 is an ~8.7% drop from the 103 peak reached at close[3];
    # decision surfaces on day 5 (lookahead-free), cooldown blocks 6-7,
    # re-entry on 8.
    prices = [100, 101, 102, 103, 94, 94, 94, 94, 94]
    out = _run(prices, [True] * 9, 0.08, 3, "rolling_max", 2)
    assert out == [True, True, True, True, True, False, False, False, True]


def test_lookahead_free_exit_lags_one_day():
    # The crash at close[4] must NOT force day-4 out; it surfaces day 5.
    prices = [100, 101, 102, 103, 94, 94, 94, 94, 94]
    out = _run(prices, [True] * 9, 0.08, 3, "rolling_max", 2)
    assert out[4] is True and out[5] is False


def test_point_to_point_ignores_shallow_intrawindow_drop():
    # At the day rolling_max fires (index 5: 94 vs the 103 peak reached 2 days
    # earlier), point_to_point compares against close[1]=101 (exactly `window`
    # days back) -> only -6.9%, so it does NOT fire there. This is the mode
    # difference at the peak-relative moment. (A later window-spaced drop in the
    # flat 94 tail can still trigger p2p, so we assert the index-5 contrast, not
    # lifelong immunity.)
    prices = [100, 101, 102, 103, 94, 94, 94, 94, 94]
    rmax = _run(prices, [True] * 9, 0.08, 3, "rolling_max", 2)
    p2p = _run(prices, [True] * 9, 0.08, 3, "point_to_point", 2)
    assert rmax[5] is False       # rolling_max exited at the peak-relative drop
    assert p2p[5] is True         # point_to_point did not fire at index 5


def test_point_to_point_triggers_on_deep_window_drop():
    # close[4]=90 vs close[1]=101 (3 days earlier) is -10.9% -> p2p fires.
    prices = [100, 101, 102, 103, 90, 90, 90, 90, 90]
    p2p = _run(prices, [True] * 9, 0.08, 3, "point_to_point", 2)
    assert p2p[5] is False


def test_slow_drift_escapes_both_modes():
    # ~2%/day decline: no single 3-day window loses 8% -> neither stop fires.
    prices = [100, 98, 96, 94, 92, 90]
    assert all(_run(prices, [True] * 6, 0.08, 3, "rolling_max", 2))
    assert all(_run(prices, [True] * 6, 0.08, 3, "point_to_point", 2))


def test_trend_exit_takes_precedence_without_cooldown():
    # Flat prices, trend forces out on day 2; re-entry is immediate on day 3
    # (a trend exit must NOT start a cooldown).
    prices = [100] * 5
    out = _run(prices, [True, True, False, True, True], 0.08, 3, "rolling_max", 2)
    assert out == [True, True, False, True, True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_velocity_stop.py -v`
Expected: FAIL — `SMATrendFollowing.__init__() got an unexpected keyword argument 'velocity_stop_pct'`.

- [ ] **Step 3: Add the `_apply_velocity_stop` method to `BaseStrategy`**

Insert after `_apply_trailing_stop` returns (after `strat_backtest.py:306`):

```python
    def _apply_velocity_stop(self, df, price=None):
        """Fixed-window ("velocity") stop: exits when the reference price has
        fallen velocity_stop_pct within a trailing window of
        velocity_stop_window trading days, rather than from the running peak
        since entry. Two modes:
          - "rolling_max": breach when the lagged close is velocity_stop_pct
            below the MAX lagged close over the trailing window.
          - "point_to_point": breach when the lagged close is velocity_stop_pct
            below the lagged close velocity_stop_window trading days earlier.

        Lookahead-free by construction (same lag convention as
        _apply_trailing_stop): every read below uses close_lagged, i.e.
        close[i-1] and earlier, never close[i]. Cooldown and precedence match
        _apply_trailing_stop: a trend-signal exit wins over a breach on the
        same day and does NOT start a cooldown; only a stop breach does. The
        window spans the trailing price series regardless of entry date (a
        market-velocity measure); the stop only APPLIES while in a position,
        and never triggers on the entry day itself (mirrors the peak stop's
        hold-on-entry behavior)."""
        trend_in_market = df['in_market'].to_numpy()
        close = (df['Close'] if price is None else price).to_numpy()
        close_lagged = np.roll(close, 1)
        if len(close_lagged):
            close_lagged[0] = close[0]
        n = len(df)
        window = self.velocity_stop_window
        pct = self.velocity_stop_pct
        mode = self.velocity_stop_mode
        final = np.zeros(n, dtype=bool)

        was_in = False
        cooldown = 0
        for i in range(n):
            if cooldown > 0:
                final[i] = False
                cooldown -= 1
                was_in = False
                continue
            if not trend_in_market[i]:
                final[i] = False
                was_in = False
                continue
            if not was_in:
                was_in = True
                final[i] = True
                continue
            if mode == "point_to_point":
                j = i - window
                breached = j >= 0 and close_lagged[i] < close_lagged[j] * (1 - pct)
            else:  # rolling_max
                lo = max(0, i - window + 1)
                ref = close_lagged[lo:i + 1].max()
                breached = close_lagged[i] < ref * (1 - pct)
            if breached:
                final[i] = False
                was_in = False
                cooldown = self.velocity_stop_cooldown_days
            else:
                final[i] = True

        return pd.Series(final, index=df.index)
```

- [ ] **Step 4: Add the four params to `SMATrendFollowing.__init__`**

Extend the signature (`strat_backtest.py:381-383`) by appending:
`velocity_stop_pct=None, velocity_stop_window=30, velocity_stop_mode="rolling_max", velocity_stop_cooldown_days=60`

After the existing `if trailing_stop_pct:` name block (after line 398), add:

```python
        if velocity_stop_pct:
            name += (f" [Velocity Stop {velocity_stop_pct*100:.1f}%/"
                     f"{velocity_stop_window}d {velocity_stop_mode}, "
                     f"cooldown {velocity_stop_cooldown_days}d]")
```

After `self.trailing_stop_cooldown_days = trailing_stop_cooldown_days` (line 449) add:

```python
        # Velocity (fixed-window) stop — mutually exclusive with the peak
        # trailing stop above; exits on a velocity_stop_pct drop within a
        # trailing velocity_stop_window-day window (see _apply_velocity_stop).
        self.velocity_stop_pct = velocity_stop_pct
        self.velocity_stop_window = velocity_stop_window
        self.velocity_stop_mode = velocity_stop_mode
        self.velocity_stop_cooldown_days = velocity_stop_cooldown_days
```

- [ ] **Step 5: Wire the velocity stop into `SMATrendFollowing._add_indicator_logic`**

Replace the peak-stop block (`strat_backtest.py:573-574`):

```python
        if self.trailing_stop_pct:
            df['in_market'] = self._apply_trailing_stop(df)
        elif self.velocity_stop_pct:
            df['in_market'] = self._apply_velocity_stop(df)
```

- [ ] **Step 6: Add the four params + wiring to `DualSignalAgreement`**

In `__init__` (`strat_backtest.py:585-586`) append the same four kwargs. After the existing `if trailing_stop_pct:` name block add the same velocity name block as Step 4. After `self.trailing_stop_cooldown_days = ...` (line 598) add the same four `self.velocity_stop_*` assignments.

In `_add_indicator_logic`, replace the peak-stop block (`strat_backtest.py:635-641`) so velocity is handled with the same `^GSPC` reference:

```python
        if self.trailing_stop_pct:
            df['trend_in_market'] = df['in_market'].copy()
            gspc_close = get_cached_signals("^GSPC")["Close"].reindex(df.index).ffill()
            df['in_market'] = self._apply_trailing_stop(df, price=gspc_close)
        elif self.velocity_stop_pct:
            df['trend_in_market'] = df['in_market'].copy()
            gspc_close = get_cached_signals("^GSPC")["Close"].reindex(df.index).ffill()
            df['in_market'] = self._apply_velocity_stop(df, price=gspc_close)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_velocity_stop.py -v`
Expected: PASS (6 tests).

- [ ] **Step 8: Commit**

```bash
git add backtest/strat_backtest.py tests/test_velocity_stop.py
git commit -m "feat: add fixed-window (velocity) trailing stop to BaseStrategy"
```

---

### Task 2: Velocity stop sweep + rolling/crash comparison

**Files:**
- Create: `backtest/velocity_stop_sweep.py` (+ `backtest/velocity_stop_sweep_output.md` on run).

**Interfaces:**
- Consumes: `SMATrendFollowing`, `DualSignalAgreement`, `Backtester` (single-run event decline), `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` from `strat_backtest`; `EVENTS`, `event_decline`, `get_equity_curve` from `trailing_stop_sweep`.
- Produces: a chosen `(mode, window, pct, cooldown)` printed as "SELECTED VELOCITY VARIANT" for Task 3 to reuse.

- [ ] **Step 1: Write the selection-phase sweep**

Create `backtest/velocity_stop_sweep.py`. Mirror `trailing_stop_sweep.py`'s single-run event-relative structure. Grid and setups:

```python
"""
Selection + evaluation sweep for the fixed-window ("velocity") trailing stop
vs the existing peak-based stop. Selection phase reuses trailing_stop_sweep's
single-run event-relative decline (^NDX/3x, S&P signal); evaluation phase
runs the chosen variant(s) through the full rolling Table-4 comparison.

Run manually:
    python backtest/velocity_stop_sweep.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, DualSignalAgreement, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)
from backtest.trailing_stop_sweep import EVENTS, event_decline, get_equity_curve

OUTPUT_PATH = REPO_ROOT / "backtest" / "velocity_stop_sweep_output.md"

MODES = ["rolling_max", "point_to_point"]
WINDOW_GRID = [20, 30, 60]
PCT_GRID = [0.06, 0.08, 0.10, 0.12]
COOLDOWN_GRID = [20, 40, 60]
PERIOD_YEARS = 26
LEVERAGE_CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR = 2.5
```

- [ ] **Step 2: Selection loop (event-relative, single run, S&P-signal setup)**

For each `(mode, window, pct, cooldown)` build an `SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True, velocity_stop_pct=pct, velocity_stop_window=window, velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown)`, get its equity curve via `get_equity_curve(strat)`, and record each event's `event_decline`. Also compute the no-stop baseline once (`SMATrendFollowing(..., t2_confirmation=True)`). Rank variants by a summary score = **mean improvement across the 5 events** (stop decline − baseline decline, summed/averaged), and print a per-event table plus the ranking. Emit the top variant per mode as `SELECTED VELOCITY VARIANT (<mode>): pct=<>, window=<>, cooldown=<>`.

Selection code (append to the script):

```python
def selection_phase():
    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    eq_base = get_equity_curve(baseline)
    base_declines = {name: event_decline(eq_base, s, e) for name, s, e in EVENTS}

    rows = []
    for mode in MODES:
        for window in WINDOW_GRID:
            for pct in PCT_GRID:
                for cooldown in COOLDOWN_GRID:
                    strat = SMATrendFollowing(
                        sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                        velocity_stop_pct=pct, velocity_stop_window=window,
                        velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown,
                    )
                    print(f"Running {mode} pct={pct:.0%} window={window}d cooldown={cooldown}d...")
                    eq = get_equity_curve(strat)
                    if eq is None:
                        continue
                    improvements = []
                    per_event = {}
                    for name, s, e in EVENTS:
                        sd = event_decline(eq, s, e)
                        bd = base_declines[name]
                        per_event[name] = sd
                        if sd is not None and bd is not None:
                            improvements.append(sd - bd)
                    rows.append({
                        "mode": mode, "window": window, "pct": pct, "cooldown": cooldown,
                        "avg_improvement": sum(improvements) / len(improvements) if improvements else float("nan"),
                        "per_event": per_event,
                    })
    return base_declines, rows
```

- [ ] **Step 3: Evaluation phase — rolling Table-4 comparison of chosen variant(s)**

Take the best variant per mode (max `avg_improvement`), plus the two anchors (no-stop dual-signal, and the peak-8%/60d stop), and run them through `run_experiment_suite` on `["^NDX", "^GSPC"]` at 3x, reusing `compare_signal_hybrid.py`'s `run_setup` pattern. For each, emit Avg/Med/Worst TWR, Worst DD, Avg Trades. Include both the S&P-signal[T+2] and dual-signal-agreement carriers for the chosen variant so the comparison spans both live-relevant setups:

```python
def rolling_row(label, strat):
    tickers = ["^NDX", "^GSPC"]
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[LEVERAGE_CONFIG], strategies=[strat], start_dates=start_dates,
        period_years=PERIOD_YEARS, annual_dca=0, base_ticker="^NDX",
        signal_ticker=("^GSPC" if isinstance(strat, SMATrendFollowing) else None),
        initial_fund=10000, apply_tax=False, print_summary=False,
    )
    df_res = results[LEVERAGE_CONFIG["name"]]
    summary = summarize_rolling_results(df_res, [strat], metric_label="TWR")
    if not summary:
        return None
    r = dict(summary[0]); r["Label"] = label; r["n_windows"] = len(df_res)
    return r
```

Build the evaluation strategy list from the selected variants (peak stop `trailing_stop_pct=0.08, trailing_stop_cooldown_days=60`; velocity winners with their swept params on both `SMATrendFollowing(..., t2_confirmation=True, signal=^GSPC)` and `DualSignalAgreement(..., t2_confirmation=False)`).

- [ ] **Step 4: Render both tables and write output**

Print (a) the selection ranking table (columns: Mode, Window, Pct, Cooldown, per-event declines, Avg Improvement) and (b) the rolling evaluation table (Setup, Avg/Med/Worst TWR, Worst DD, Avg Trades, Windows). Write the concatenation to `OUTPUT_PATH`.

- [ ] **Step 5: Run and cross-validate**

Run: `python backtest/velocity_stop_sweep.py`
Expected: completes, writes `velocity_stop_sweep_output.md`, and the rolling **no-stop dual-signal** anchor row matches README Table 4's `Dual-signal agreement` row (Avg TWR ≈ 25.81%, Worst DD ≈ -84.95%) and the **peak-8%/60d** anchor matches Table 4's stopped rows (Worst DD ≈ -64.78%). If anchors don't match, stop and diagnose before trusting velocity numbers.

- [ ] **Step 6: Commit**

```bash
git add backtest/velocity_stop_sweep.py backtest/velocity_stop_sweep_output.md
git commit -m "feat: add velocity-stop selection+rolling sweep vs peak stop"
```

---

### Task 3: Add chosen velocity variant to the crash table

**Files:**
- Modify: `backtest/crash_event_drawdown.py` — extend `build_strategies()` (lines 39-52).

**Interfaces:**
- Consumes: the `SELECTED VELOCITY VARIANT` params from Task 2's output.

- [ ] **Step 1: Add velocity rows to `build_strategies()`**

Append two rows using the selected `(mode, window, pct, cooldown)` from Task 2 (fill in the actual chosen values — read them from `velocity_stop_sweep_output.md`). Example shape (replace `PCT/WINDOW/MODE/CD` with the selected values):

```python
        ("E: SMA + T+2 + GSPC velocity PCT/WINDOWd",
         SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                           velocity_stop_pct=PCT, velocity_stop_window=WINDOW,
                           velocity_stop_mode="MODE", velocity_stop_cooldown_days=CD)),
        ("F: Dual-signal + GSPC velocity PCT/WINDOWd",
         DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                             velocity_stop_pct=PCT, velocity_stop_window=WINDOW,
                             velocity_stop_mode="MODE", velocity_stop_cooldown_days=CD)),
```

- [ ] **Step 2: Run and verify**

Run: `python backtest/crash_event_drawdown.py`
Expected: table now has E/F rows across all 5 events; existing A–D rows unchanged vs README Table 5 (Buy&Hold dot-com ≈ -99.95%, B dot-com ≈ -51.11%). The velocity rows show the slow-bear behavior (compare E/F dot-com & 2022 cells against B/D — this is the slow-bear-leak read).

- [ ] **Step 3: Commit**

```bash
git add backtest/crash_event_drawdown.py backtest/crash_event_drawdown_output.md
git commit -m "feat: add velocity-stop variants to crash-event drawdown table"
```

---

### Task 4: QQQ (1x) full strategy sweep

**Files:**
- Create: `backtest/qqq_strategy_sweep.py` (+ `_output.md` on run).

**Interfaces:**
- Consumes: `SMATrendFollowing`, `DualSignalAgreement`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results`, `BuyAndHold`.

- [ ] **Step 1: Write the QQQ sweep script**

Create `backtest/qqq_strategy_sweep.py`, mirroring `compare_signal_hybrid.py` but with `LEVERAGE_CONFIG = {"name": "1x", "leverage": 1, "expense": 0.0020}` (QQQ's expense ratio). Reuse the full setup list from `compare_signal_hybrid.py`'s `SETUPS` (NDX-own, S&P-signal, dual-signal; ±T+2; + the peak-8%/60d stop on the two live-relevant carriers). Base ticker `^NDX`, so the engine models 1x NASDAQ-100 (= QQQ) with the ETF expense drag. Add a `BuyAndHold()` row for reference. Header: `### QQQ (1x) — Strategy Comparison (SMA 200, ATR x2.5)`.

- [ ] **Step 2: Run and cross-check**

Run: `python backtest/qqq_strategy_sweep.py`
Expected: writes `qqq_strategy_sweep_output.md`. Sanity check: the `NDX own signal [T+2]` 1x row should land near README Table 1's `1x SMA 200 (ATR x2.5, T+2)` Avg TWR (~13.89%) — not identical (Table 1 uses TQQQ-style 0.0095 expense; this uses 0.0020), but same ballpark and clearly above 1x Buy&Hold.

- [ ] **Step 3: Commit**

```bash
git add backtest/qqq_strategy_sweep.py backtest/qqq_strategy_sweep_output.md
git commit -m "feat: add QQQ (1x) full strategy sweep"
```

---

### Task 5: Taxable-account (after-tax) comparison

**Files:**
- Create: `backtest/taxable_account_comparison.py` (+ `_output.md` on run).

**Interfaces:**
- Consumes: `SMATrendFollowing`, `DualSignalAgreement`, `Backtester` (for `total_tax_paid`), `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results`.

- [ ] **Step 1: Write the taxable comparison script**

Create `backtest/taxable_account_comparison.py`. For each key setup (S&P-signal[T+2], S&P-signal[T+2]+peak-stop 8/60, dual-signal, dual-signal+peak-stop 8/60; all ^NDX/3x/ATR2.5), run the rolling suite **twice** — once `apply_tax=False`, once `apply_tax=True` — via `run_experiment_suite`, and report per setup: Pre-Tax Avg TWR, After-Tax Avg TWR, Tax Drag (pp) = pre − after, After-Tax Worst DD, Avg Trades. Reuse the `run_setup`/`summarize_rolling_results` pattern from `compare_signal_hybrid.py`. Header: `### Taxable Account — Pre-Tax vs After-Tax (^NDX/3x, 25%/15% rates)`. Note in the script docstring that rates are the engine defaults (`TAX_SHORT_TERM_RATE=25%`, `TAX_LONG_TERM_RATE=15%`).

- [ ] **Step 2: Run and verify direction**

Run: `python backtest/taxable_account_comparison.py`
Expected: writes `taxable_account_comparison_output.md`; after-tax TWR < pre-tax for every row (tax drag > 0), and the stopped setups (more trades, more short-term gains) show **larger** tax drag than their no-stop counterparts — the point of the table. Pre-tax rows should match README Table 4 (dual-signal Avg TWR ≈ 25.81%).

- [ ] **Step 3: Commit**

```bash
git add backtest/taxable_account_comparison.py backtest/taxable_account_comparison_output.md
git commit -m "feat: add taxable-account pre-tax vs after-tax comparison"
```

---

### Task 6: README tables + docs finding notes

**Files:**
- Modify: `README.md` — add Table 6 (velocity stop vs peak, rolling + crash read), Table 7 (QQQ 1x), Table 8 (taxable account); update the Table-list bullets near line 71.
- Create: `docs/velocity-stop-2026-08-06.md`, `docs/qqq-1x-comparison-2026-08-06.md`, `docs/taxable-account-2026-08-06.md`.

**Interfaces:**
- Consumes: the `_output.md` files from Tasks 2–5.

- [ ] **Step 1: Add the three README tables**

Paste the generated tables (from the `_output.md` files) into `README.md` after Table 5, each with an interpretive note in the existing voice. The velocity note must explicitly answer the driving question: does the velocity stop cut whipsaws (Table-4 trade count) **and** still catch slow bears (dot-com/2022 crash cells), or does it leak. Update the "Tables 1–5" summary bullets (~line 71) to include the new tables.

- [ ] **Step 2: Add the caveat block to each new table**

Each table carries: the overlapping-window caveat; that velocity is a single non-OOS-validated selection run (same bar as the Table-4 caveat); and, for QQQ, that it uses `^NDX` index data with QQQ's expense ratio, not QQQ's own post-1999 price history.

- [ ] **Step 3: Write the three docs finding notes**

Each `docs/*.md` follows the `docs/trailing-stop-*` chain style: what was tested, method, result table, interpretation, caveats, and what a follow-up would check (e.g. OOS validation of the velocity winner).

- [ ] **Step 4: Verify README renders**

Run: `python -c "import pathlib; print('OK' if 'Table 6' in pathlib.Path('README.md').read_text(encoding='utf-8') or 'Velocity' in pathlib.Path('README.md').read_text(encoding='utf-8') else 'MISSING')"`
Expected: `OK`. Eyeball the mermaid/tables visually if possible.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/velocity-stop-2026-08-06.md docs/qqq-1x-comparison-2026-08-06.md docs/taxable-account-2026-08-06.md
git commit -m "docs: add velocity-stop, QQQ-1x, and taxable-account tables + findings"
```

---

## Self-Review

**Spec coverage:**
- Velocity stop mechanism (both modes, lookahead-free, cooldown, ^GSPC ref) → Task 1. ✅
- Velocity sweep (mode×window×pct×cooldown) + rolling + crash lenses → Tasks 2, 3. ✅
- QQQ full sweep at 1x → Task 4. ✅
- Taxable table (25%/15%, pre vs after) → Task 5. ✅
- README tables + docs notes + caveats → Task 6. ✅
- Option A (separate method, peak stop untouched, mutually exclusive) → Task 1 constraints + wiring. ✅
- Tests for the new method → Task 1. ✅

**Placeholder scan:** The only intentional deferred values are the *selected* velocity params in Task 3/Task 6, which are data-driven outputs of Task 2 — the plan tells the implementer to read them from `velocity_stop_sweep_output.md`. All engine code and tests are concrete. ✅

**Type consistency:** `_apply_velocity_stop(self, df, price=None) -> pd.Series` used identically in Tasks 1–2; param names `velocity_stop_pct/_window/_mode/_cooldown_days` consistent across constructors, wiring, tests, and all scripts; `velocity_stop_mode` values `"rolling_max"`/`"point_to_point"` consistent throughout. ✅
