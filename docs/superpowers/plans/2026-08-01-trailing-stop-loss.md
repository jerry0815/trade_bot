# Trailing Stop-Loss (Open-Position Risk Management) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in trailing-stop-loss mechanism to `SMATrendFollowing` that exits an open position when price falls a fixed % below its own peak since entry (independent of the slow SMA/ATR trend signal), blocks re-entry for a fixed cooldown period, then validate whether it actually shrinks the dot-com crash's -83% episode without being a fragile one-off or narrowly event-specific.

**Architecture:** Two new opt-in constructor params on `SMATrendFollowing` (`trailing_stop_pct`, `trailing_stop_cooldown_days`), default `None`/off, byte-identical when unset. The mechanism is a sequential post-processing overlay applied to the already-computed `in_market` column inside `_add_indicator_logic` — it can only be sequential (not vectorized like the rest of the file) because the peak-since-entry depends on when *this overlay itself* last opened a position, which depends on its own prior output. Two new standalone scripts follow this project's existing `generate_*`/`*_comparison.py` pattern: an event-relative sweep across a parameter grid, and a rolling-window + segmentation validation for whatever candidate(s) the sweep turns up. A markdown finding doc captures the result either way (positive or negative).

**Tech Stack:** Python 3.11, pandas, numpy — same as the rest of the project. No new dependencies.

**Full design context:** `docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md` (read its two addenda too — both correct the original design based on data discovered while writing this plan).

## Global Constraints

- **Both new params default `None`/off; unset behavior must be byte-identical** to current `SMATrendFollowing` output — same invariant already verified for `vix_threshold`/`atr_spike_multiplier`/`sma_slope_lookback` (see `docs/session-handover-2026-08-01.md` Phase 5-7).
- **Trailing-stop trigger is measured against the signal-ticker's unleveraged `Close`**, not the leveraged equity curve — per the design's Measurement-basis decision. Do not measure against `equity_curve`.
- **A trailing-stop-triggered exit is immediate — it bypasses `t2_confirmation` unconditionally.** It does not go through the `rolling(2).min()` T+2 gate, regardless of the strategy's `t2_confirmation` setting.
- **Cooldown blocks re-entry for `trailing_stop_cooldown_days` trading days after a stop-triggered exit only** — a normal trend-signal-driven exit (SMA/ATR band says sell) does NOT start a cooldown.
- **Peak resets on every new entry**, never persists across a cash period or across trades.
- **Sweep grid is `trailing_stop_pct ∈ {5%, 7%, 8%, 10%, 12%, 15%, 20%}` × `trailing_stop_cooldown_days ∈ {10, 20, 40, 60}`** (28 combinations) — corrected from the design doc's original 10-30% range after discovering the dot-com trade's peak-to-trough on the underlying-price basis is only ~-13% (see design doc Component 2 addendum).
- **Event-specificity segmentation is by window START DATE band (1998-01-01 to 2001-12-31) vs. all other starts** — not "contains dot-com y/n" (every one of the 172 rolling windows already contains the dot-com period; see design doc Component 4).
- **No change to `bot.py`, live trading behavior, or README** — this stays an opt-in experimental param, same status as `vix_threshold`/`atr_spike_multiplier`/`sma_slope_lookback`. No CHANGELOG.md entry either — checked: neither of those three params' commits (`9dc6c5a`, `c714166`) added one; that convention is reserved for adopted/published features.

---

### Task 1: Implement `trailing_stop_pct` / `trailing_stop_cooldown_days` on `SMATrendFollowing`

**Files:**
- Modify: `backtest/strat_backtest.py:249-295` (`SMATrendFollowing.__init__`)
- Modify: `backtest/strat_backtest.py:333-414` (`SMATrendFollowing._add_indicator_logic`)

**Interfaces:**
- Produces: `SMATrendFollowing(..., trailing_stop_pct=None, trailing_stop_cooldown_days=20)`. When `trailing_stop_pct` is `None` (default), `_add_indicator_logic` output is byte-identical to today. When set, a new method `SMATrendFollowing._apply_trailing_stop(self, df)` returns a `pd.Series` (bool, same index as `df`) that replaces `df['in_market']`.

- [ ] **Step 1: Capture a baseline BEFORE changing any code**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.strat_backtest import SMATrendFollowing, Backtester
env = Backtester(base_ticker='^NDX', signal_ticker='^GSPC', start_date='1986-04-29', period_years=40, leverage=3, expense_ratio=0.0095, initial_fund=10000, verbose=False)
strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
res = env.run(strat)
print('strategy_twr:', res['strategy_twr'])
print('max_drawdown:', res['max_drawdown'])
print('total_trades:', res['total_trades'])
for t in res['trade_log']:
    if t['entry_date'].year in (1999, 2000):
        print(' trade:', t['entry_date'].date(), '->', t['exit_date'].date(), f\"{t['hold_days']}d\", f\"{t['gross_ret_pct']:.2f}%\")
"
```
Record the exact printed output. Expected (verified while writing this plan): `total_trades` includes exactly one trade with `entry_date` 1999-11-12 and `exit_date` 2000-10-12 (335 days, the dot-com episode).

- [ ] **Step 2: Add the two new constructor params**

Replace `backtest/strat_backtest.py:249-263`:
```python
class SMATrendFollowing(BaseStrategy):
    def __init__(self, sma_window=200, buffer_pct=None, atr_multiplier=2.5, t2_confirmation=False,
                 vix_threshold=None, atr_spike_multiplier=None, atr_spike_lookback=60,
                 sma_slope_lookback=None):
        # We handle naming and initialization cleanly
        name = f"SMA {sma_window} - " + (f"Static {buffer_pct*100}% Buffer" if buffer_pct else f"ATR Buffer (x{atr_multiplier})")
        if t2_confirmation:
            name += " [T+2]"
        if vix_threshold:
            name += f" [VIX>{vix_threshold} bypass]"
        if atr_spike_multiplier:
            name += f" [ATR-spike x{atr_spike_multiplier} bypass]"
        if sma_slope_lookback:
            name += f" [SMA-slope {sma_slope_lookback}d re-entry filter]"
        super().__init__(name=name)
```
with:
```python
class SMATrendFollowing(BaseStrategy):
    def __init__(self, sma_window=200, buffer_pct=None, atr_multiplier=2.5, t2_confirmation=False,
                 vix_threshold=None, atr_spike_multiplier=None, atr_spike_lookback=60,
                 sma_slope_lookback=None, trailing_stop_pct=None, trailing_stop_cooldown_days=20):
        # We handle naming and initialization cleanly
        name = f"SMA {sma_window} - " + (f"Static {buffer_pct*100}% Buffer" if buffer_pct else f"ATR Buffer (x{atr_multiplier})")
        if t2_confirmation:
            name += " [T+2]"
        if vix_threshold:
            name += f" [VIX>{vix_threshold} bypass]"
        if atr_spike_multiplier:
            name += f" [ATR-spike x{atr_spike_multiplier} bypass]"
        if sma_slope_lookback:
            name += f" [SMA-slope {sma_slope_lookback}d re-entry filter]"
        if trailing_stop_pct:
            name += f" [Trailing Stop {trailing_stop_pct*100:.0f}%, cooldown {trailing_stop_cooldown_days}d]"
        super().__init__(name=name)
```

Then after `backtest/strat_backtest.py:295`'s `self.sma_slope_lookback = sma_slope_lookback` line, add:
```python
        # When set, exits the position the day the signal-ticker's Close
        # falls trailing_stop_pct below its own running peak since the most
        # recent entry — independent of what the SMA/ATR trend signal says.
        # Measured against the unleveraged signal-ticker price (same series
        # the entry/exit band already watches), not the leveraged equity
        # curve: a given % threshold then means the same underlying move
        # regardless of leverage tier, instead of needing separate tuning
        # per leverage config. Acts immediately (bypasses t2_confirmation
        # unconditionally) — the whole point is reacting faster than the
        # slow trend signal, so gating it behind the same delay it exists
        # to route around would defeat the purpose. After a stop-triggered
        # exit, re-entry is blocked for trailing_stop_cooldown_days trading
        # days regardless of the trend signal, then normal signal-driven
        # entry logic resumes unmodified. A normal trend-signal-driven exit
        # does NOT start a cooldown — only a trailing-stop-triggered one
        # does. cooldown_days only matters when trailing_stop_pct is set.
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_cooldown_days = trailing_stop_cooldown_days
```

- [ ] **Step 3: Add the overlay application + `_apply_trailing_stop` method**

Replace `backtest/strat_backtest.py:410-414`:
```python
        # 7. Shift the signal by 1 day and strictly cast to bool
        df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)

        return df
```
with:
```python
        # 7. Shift the signal by 1 day and strictly cast to bool
        df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)

        # 8. Trailing-stop overlay (opt-in). Must run AFTER the vectorized
        # state machine above, not fused into it: the trailing stop's peak
        # tracking depends on when THIS overlay itself last opened a
        # position, which depends on its own prior output — inherently
        # sequential, unlike the band/T+2/bypass logic above.
        if self.trailing_stop_pct:
            df['in_market'] = self._apply_trailing_stop(df)

        return df

    def _apply_trailing_stop(self, df):
        """
        Walks the already-computed (execution-day) in_market column day by
        day. Tracks the running peak Close since the most recent entry;
        forces an exit the day Close falls trailing_stop_pct below that
        peak, regardless of the trend signal. After a stop-triggered exit,
        forces in_market False for the next trailing_stop_cooldown_days
        trading days even if the trend signal says in-market again; normal
        trend-driven logic resumes once the cooldown elapses.
        """
        trend_in_market = df['in_market'].to_numpy()
        close = df['Close'].to_numpy()
        n = len(df)
        final = np.zeros(n, dtype=bool)

        was_in = False
        peak = 0.0
        cooldown = 0

        for i in range(n):
            if cooldown > 0:
                final[i] = False
                cooldown -= 1
                was_in = False
                continue

            desired = trend_in_market[i]
            if not desired:
                final[i] = False
                was_in = False
                continue

            if not was_in:
                # Fresh entry (first entry, or re-entry after a cash
                # period/cooldown): peak starts at today's close.
                peak = close[i]
                was_in = True
                final[i] = True
                continue

            # Already holding: update the peak, then check the stop.
            peak = max(peak, close[i])
            if close[i] < peak * (1 - self.trailing_stop_pct):
                final[i] = False
                was_in = False
                cooldown = self.trailing_stop_cooldown_days
            else:
                final[i] = True

        return pd.Series(final, index=df.index)
```

- [ ] **Step 4: Re-run the exact Step 1 baseline and diff**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.strat_backtest import SMATrendFollowing, Backtester
env = Backtester(base_ticker='^NDX', signal_ticker='^GSPC', start_date='1986-04-29', period_years=40, leverage=3, expense_ratio=0.0095, initial_fund=10000, verbose=False)
strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
res = env.run(strat)
print('strategy_twr:', res['strategy_twr'])
print('max_drawdown:', res['max_drawdown'])
print('total_trades:', res['total_trades'])
for t in res['trade_log']:
    if t['entry_date'].year in (1999, 2000):
        print(' trade:', t['entry_date'].date(), '->', t['exit_date'].date(), f\"{t['hold_days']}d\", f\"{t['gross_ret_pct']:.2f}%\")
"
```
Expected: identical output to Step 1 — proves the default (`trailing_stop_pct=None`) path is unaffected.

- [ ] **Step 5: Confirm the mechanism actually fires and behaves as designed**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.strat_backtest import SMATrendFollowing, Backtester
env = Backtester(base_ticker='^NDX', signal_ticker='^GSPC', start_date='1986-04-29', period_years=40, leverage=3, expense_ratio=0.0095, initial_fund=10000, verbose=False)
strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True, trailing_stop_pct=0.10, trailing_stop_cooldown_days=20)
res = env.run(strat)
for t in res['trade_log']:
    if t['entry_date'].year in (1999, 2000):
        print('trade:', t['entry_date'].date(), '->', t['exit_date'].date(), f\"{t['hold_days']}d\", f\"{t['gross_ret_pct']:.2f}%\")
"
```
Expected (verified while writing this plan, via a standalone prototype of the same algorithm against real `^GSPC` data): the single 335-day 1999-11-12 → 2000-10-12 baseline trade is now split into **two** trades — `1999-11-12 -> 2000-04-14` (the trailing stop firing near the true March 2000 top) and a **re-entry** `2000-05-16 -> 2000-10-11` (the trend signal recovers during the bear-market rally, cooldown has already elapsed by then, so the strategy goes back in and rides most of the rest of the decline before the trend signal's own exit fires). This is expected, real behavior, not a bug — it's exactly the kind of partial-protection-with-a-whipsaw-risk outcome the design's re-entry-cooldown discussion anticipated, and it's why Tasks 2-4 validate net effect empirically rather than assuming the split trade is automatically an improvement.

- [ ] **Step 6: Commit**

```bash
git add backtest/strat_backtest.py
git commit -m "feat: add trailing-stop-loss mechanism to SMATrendFollowing"
```

---

### Task 2: Write `backtest/trailing_stop_sweep.py`

**Files:**
- Create: `backtest/trailing_stop_sweep.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `SMATrendFollowing`, `Backtester` from `backtest.strat_backtest` (Task 1's new params).
- Produces: prints and writes `backtest/trailing_stop_sweep_output.md` — one row per (pct, cooldown, event) combination with `Baseline Decline`, `Stop Decline`, `Improvement (pp)` columns.

- [ ] **Step 1: Write the script**

```python
"""
Sweeps trailing_stop_pct x trailing_stop_cooldown_days for SMATrendFollowing
against the live bot.py config (S&P-signal-driven, ^NDX/3x), reporting
event-relative decline for all 5 known crises per combination. Same
event-relative methodology as backtest/event_leverage_comparison.py: each
event's decline is measured from the equity value at/just-before the
event's well-known start date to the local trough within the event window,
independent of whether an earlier, still-unresolved drawdown was already
in progress.

Run manually:
    python backtest/trailing_stop_sweep.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing, Backtester

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_sweep_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
LEVERAGE = 3
EXPENSE = 0.0095

# Corrected grid (see docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md
# Component 2 addendum): measured against the underlying signal-ticker price,
# the dot-com trade's peak-to-trough was only ~-13%, so the real effect lives
# in the 5-20% range, not the original 10-30% estimate (which was based on
# the leveraged equity curve).
PCT_GRID = [0.05, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20]
COOLDOWN_GRID = [10, 20, 40, 60]

EVENTS = [
    ("Black Monday 1987",    "1987-08-25", "1987-12-04"),
    ("Dot-com crash",        "2000-03-24", "2002-10-09"),
    ("2008 GFC",             "2007-10-09", "2009-03-09"),
    ("COVID crash",          "2020-02-19", "2020-03-23"),
    ("2022 rate-shock bear", "2022-01-03", "2022-10-12"),
]


def get_equity_curve(strategy):
    env = Backtester(
        base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER, start_date="1986-04-29",
        period_years=40, leverage=LEVERAGE, expense_ratio=EXPENSE,
        initial_fund=10000, verbose=False,
    )
    res = env.run(strategy)
    return res["equity_curve"] if res else None


def event_decline(equity, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start < equity.index[0]:
        return None
    local_peak_date = equity.loc[:start].index[-1]
    local_peak = equity.loc[local_peak_date]
    trough = equity.loc[start:end].min()
    return (trough / local_peak - 1) * 100


if __name__ == "__main__":
    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    eq_baseline = get_equity_curve(baseline)

    rows = []
    for pct in PCT_GRID:
        for cooldown in COOLDOWN_GRID:
            strat = SMATrendFollowing(
                sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                trailing_stop_pct=pct, trailing_stop_cooldown_days=cooldown,
            )
            print(f"Running pct={pct:.0%} cooldown={cooldown}d...")
            eq_strat = get_equity_curve(strat)
            if eq_strat is None:
                continue
            for event_name, start, end in EVENTS:
                base_decline = event_decline(eq_baseline, start, end)
                stop_decline = event_decline(eq_strat, start, end)
                if base_decline is None or stop_decline is None:
                    continue
                rows.append({
                    "Pct": pct,
                    "Cooldown": cooldown,
                    "Event": event_name,
                    "Baseline Decline": base_decline,
                    "Stop Decline": stop_decline,
                    # Both declines are negative numbers; the stop doing
                    # better means stop_decline is LESS negative, so
                    # stop - baseline > 0 means improvement.
                    "Improvement (pp)": stop_decline - base_decline,
                })

    df = pd.DataFrame(rows)
    lines = ["### Trailing-Stop Sweep: Event-Relative Decline vs Baseline (^NDX/3x, S&P signal)", "",
             "| Pct | Cooldown | Event | Baseline Decline | Stop Decline | Improvement (pp) |",
             "| ---: | ---: | :--- | ---: | ---: | ---: |"]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['Pct']:.0%} | {r['Cooldown']:.0f}d | {r['Event']} | {r['Baseline Decline']:.2f}% "
            f"| {r['Stop Decline']:.2f}% | {r['Improvement (pp)']:+.2f} |"
        )
    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
```

- [ ] **Step 2: Smoke-test on a single combination before the full 28-combination sweep**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.trailing_stop_sweep import get_equity_curve, event_decline, EVENTS
from backtest.strat_backtest import SMATrendFollowing
baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True, trailing_stop_pct=0.10, trailing_stop_cooldown_days=20)
eq_b = get_equity_curve(baseline)
eq_s = get_equity_curve(strat)
for name, start, end in EVENTS:
    print(name, event_decline(eq_b, start, end), '->', event_decline(eq_s, start, end))
"
```
Expected: 5 lines print, no tracebacks. The 'Dot-com crash' row should show `eq_s`'s decline noticeably less negative than `eq_b`'s (the trailing stop should measurably help this specific case, per Task 1 Step 5's finding).

- [ ] **Step 3: Add the scratch output file to `.gitignore`**

Append to `.gitignore`:
```
backtest/trailing_stop_sweep_output.md
```

- [ ] **Step 4: Commit**

```bash
git add backtest/trailing_stop_sweep.py .gitignore
git commit -m "feat: add trailing-stop event-relative sweep script"
```

---

### Task 3: Run the sweep, select candidate(s), write `backtest/trailing_stop_validate.py`

**Files:**
- Modify: `.gitignore`
- Create: `backtest/trailing_stop_validate.py` (only if at least one candidate survives Step 2's selection criteria — see Step 3's branch)

**Interfaces:**
- Consumes: `backtest/trailing_stop_sweep_output.md` (Task 2's output).
- Produces (if a candidate is found): `backtest/trailing_stop_validate.py`, consuming `SMATrendFollowing`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` from `backtest.strat_backtest`.

- [ ] **Step 1: Run the full sweep**

```bash
python backtest/trailing_stop_sweep.py
```
Expect no tracebacks, 140 data rows (28 combinations x 5 events) printed and written to `backtest/trailing_stop_sweep_output.md`.

- [ ] **Step 2: Apply the candidate-selection procedure to the Dot-com rows**

Read `backtest/trailing_stop_sweep_output.md`. For each of the 28 (pct, cooldown) combinations, note the **Dot-com crash** row's `Improvement (pp)` value. Apply this exact procedure:

1. A combination is a **candidate** if its Dot-com `Improvement (pp)` is `>= 2.0`.
2. A candidate is **non-fragile** (survives) only if BOTH:
   - At least one of its pct-neighbors (the adjacent value in `PCT_GRID` one step up or down, same cooldown) also has Dot-com `Improvement (pp) >= 1.0`.
   - At least one of its cooldown-neighbors (the adjacent value in `COOLDOWN_GRID` one step up or down, same pct) also has Dot-com `Improvement (pp) >= 1.0`.

   This mirrors the non-monotonic-cliff check that flagged `atr_spike_multiplier` as too fragile in Phase 6 (a huge win at one exact value that vanished at the next) — a real effect should hold up in the neighborhood, not just at one exact combination.
3. Among all surviving non-fragile candidates, pick the **1** with the highest Dot-com `Improvement (pp)`. If two or more tie exactly, prefer the larger `cooldown` (more conservative — less likely to whipsaw back into a still-declining market).
4. If zero candidates survive Step 2, **record that explicitly** (e.g. "no combination met the non-fragility bar") — this is a valid, useful outcome. **Skip the rest of this task and Task 4 entirely; go directly to Task 5** and write up this negative finding using only the sweep data.

Record the chosen `(pct, cooldown)` pair (or the "no candidate" outcome) — it's needed for Step 3 below.

- [ ] **Step 3: If a candidate was found, write `backtest/trailing_stop_validate.py`**

Substitute the real `pct`/`cooldown` values found in Step 2 into `CANDIDATE_PCT` / `CANDIDATE_COOLDOWN` below before saving this file:

```python
"""
Rolling-window validation for the trailing-stop candidate selected from
backtest/trailing_stop_sweep_output.md (see backtest/trailing_stop_sweep.py
and docs/superpowers/plans/2026-08-01-trailing-stop-loss.md Task 3 for the
selection procedure), plus a start-date-band segmentation check.

Segmentation note (see docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md
Component 4): all 172 rolling windows' 26-year spans already include the
dot-com period (2000-2002), so a "contains dot-com y/n" split has no
non-trivial groups. This instead segments by window START date: the
1998-01-01 to 2001-12-31 band (where Phase 4's worst-10 rolling windows for
the live SMA config all land) vs. all other starts.

Run manually:
    python backtest/trailing_stop_validate.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, run_experiment_suite, warmup_aware_start_dates,
    summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_validate_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

CANDIDATE_PCT = <PCT>            # e.g. 0.10 -- fill in from Task 3 Step 2
CANDIDATE_COOLDOWN = <COOLDOWN>  # e.g. 20   -- fill in from Task 3 Step 2

WORST_BAND_START = pd.Timestamp("1998-01-01")
WORST_BAND_END = pd.Timestamp("2001-12-31")


if __name__ == "__main__":
    start_dates = warmup_aware_start_dates([BASE_TICKER, SIGNAL_TICKER], PERIOD_YEARS)

    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    candidate = SMATrendFollowing(
        sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
        trailing_stop_pct=CANDIDATE_PCT, trailing_stop_cooldown_days=CANDIDATE_COOLDOWN,
    )
    strategies = [baseline, candidate]

    print(f"Running {len(start_dates)}-window rolling backtest for {len(strategies)} strategies...")
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]

    summary = summarize_rolling_results(df_res, strategies)

    lines = [f"### Trailing-Stop Rolling-Window Validation ({len(start_dates)} windows, ^NDX/3x, S&P signal)", "",
             "| Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |",
             "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for s in summary:
        lines.append(
            f"| {s['Strategy']} | {s['Avg TWR']:.2f}% | {s['Med TWR']:.2f}% "
            f"| {s['Worst TWR']:.2f}% | {s['Worst DD']:.2f}% | {s['Avg Trades']:.1f} |"
        )

    # Segmentation: worst-window start-date band vs. everything else.
    df_res["Start Date"] = pd.to_datetime(df_res["Start Date"])
    in_band_mask = (df_res["Start Date"] >= WORST_BAND_START) & (df_res["Start Date"] <= WORST_BAND_END)
    in_band = df_res[in_band_mask]
    out_band = df_res[~in_band_mask]

    lines += ["", f"### Segmentation: worst-window start-date band ({WORST_BAND_START.date()} to {WORST_BAND_END.date()}) vs. rest", "",
              "| Strategy | Band | Avg TWR | N windows |",
              "| :--- | :--- | ---: | ---: |"]
    for s in strategies:
        ret_col = f"{s.name} TWR (%)"
        for label, sub in [(f"{WORST_BAND_START.date()} to {WORST_BAND_END.date()} starts", in_band),
                            ("Other starts", out_band)]:
            if ret_col in sub.columns and len(sub):
                lines.append(f"| {s.name} | {label} | {sub[ret_col].mean():.2f}% | {len(sub)} |")

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
```

- [ ] **Step 4: Smoke-test the candidate strategy's name/params resolve correctly**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.trailing_stop_validate import CANDIDATE_PCT, CANDIDATE_COOLDOWN
from backtest.strat_backtest import SMATrendFollowing
s = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True, trailing_stop_pct=CANDIDATE_PCT, trailing_stop_cooldown_days=CANDIDATE_COOLDOWN)
print(s.name)
"
```
Expected: prints a name string ending in `[T+2] [Trailing Stop N%, cooldown Md]` where N/M match the values recorded in Step 2 — confirms `CANDIDATE_PCT`/`CANDIDATE_COOLDOWN` were filled in correctly (not left as placeholders) before the expensive rolling run.

- [ ] **Step 5: Add the scratch output file to `.gitignore` and commit**

Append to `.gitignore`:
```
backtest/trailing_stop_validate_output.md
```

```bash
git add backtest/trailing_stop_validate.py .gitignore
git commit -m "feat: add trailing-stop rolling-window validation script"
```

---

### Task 4: Run the validation and sanity-check the output

**Skip this task entirely if Task 3 Step 2 found no candidate** — go directly to Task 5.

**Files:** none (this task only runs Task 3's script and inspects output).

- [ ] **Step 1: Run the validation**

```bash
python backtest/trailing_stop_validate.py
```
Expect no tracebacks, both tables printed, and a final "Written to backtest/trailing_stop_validate_output.md" line. This runs a 172-window rolling backtest for 2 strategies — expect it to take at least as long as a single row of the project's existing Table 1-3 generation (comparable rolling-window cost), not instant.

- [ ] **Step 2: Sanity-check the output**

Read `backtest/trailing_stop_validate_output.md`. Confirm:
- The baseline row's Avg TWR / Worst DD are in the same ballpark as this project's already-published Table 1/3 numbers for the equivalent config (SMA 200, ATR x2.5, T+2 on, S&P signal, 3x) — a wildly different number here (not just "candidate differs from baseline," but baseline differing from README) means something is broken in this script, not a real finding.
- Both segmentation rows per strategy have a plausible `N windows` split (in-band + out-of-band should sum to the total window count from Step 1's printed run).
- The candidate's Worst DD is not worse than baseline's by an amount that contradicts Task 1 Step 5's finding that this mechanism can only reduce or leave unchanged the single-episode dot-com decline it directly targets — if the candidate's Worst DD is dramatically worse than baseline's, investigate before writing up (could indicate the cooldown is causing a costly whipsaw somewhere else in history, which is itself a valid finding to report, but verify it's real and not a bug first).

If anything looks structurally broken, investigate before writing the doc — don't publish a finding built on suspect numbers.

---

### Task 5: Write up the finding

**Files:**
- Create: `docs/trailing-stop-loss-finding-2026-08-01.md`

- [ ] **Step 1: Write the finding doc**

Structure the doc with these sections. Source all numbers from `backtest/trailing_stop_sweep_output.md` and (if Task 4 ran) `backtest/trailing_stop_validate_output.md` — don't invent or approximate numbers not present in those files.

- **Method** — one paragraph summarizing the mechanism (peak-relative % stop on underlying signal-ticker price, fixed-day cooldown before signal-driven re-entry resumes), citing `docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md` for full rationale rather than repeating it.
- **Sweep result** — which (pct, cooldown) combinations, if any, met the Task 3 Step 2 selection bar; the winning combination's Dot-com `Improvement (pp)` and its effect on the other 4 events (a mechanism that helps dot-com but meaningfully hurts another event, e.g. by causing a costly whipsaw during COVID's fast crash, is worth stating plainly).
- **Rolling-window result** (only if Task 4 ran) — Avg/Med/Worst TWR and Worst DD for baseline vs. candidate across all 172 windows; state directly whether the candidate is a net improvement, a net regression, or a wash on the full-history aggregate — not just the one event it targets.
- **Segmentation result** (only if Task 4 ran) — Avg TWR for the 1998-2001-start band vs. other starts, for both strategies; state plainly whether the benefit concentrates in the already-known-worst window band or is general.
- **Verdict / recommendation** — same honest framing this project already uses for `vix_threshold` (real but narrow effect, not yet recommended for adoption) and `sma_slope_lookback` (hypothesis disproven): state whether this mechanism is a plausible `bot.py` candidate, needs further validation (e.g. out-of-sample testing per `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`'s approach), or should be shelved — driven by what the numbers actually show, not by how promising the idea sounded going in.

- [ ] **Step 2: Commit**

```bash
git add docs/trailing-stop-loss-finding-2026-08-01.md
git commit -m "docs: add trailing-stop-loss finding for dot-com crash protection"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = design's "Mechanism" + "Components §1" (SMATrendFollowing changes). Task 2 = "Components §2" (event-relative sweep, corrected grid). Task 3 = candidate selection (a concrete, mechanical procedure — not in the original design doc verbatim, but required to bridge "Components §2" sweep output into "Components §3" rolling validation) + "Components §3" (rolling-window validation script). Task 4 = running Task 3's script. Task 5 = "Components §4" (segmentation, folded into Task 3's script per the corrected mechanism) + "Output location" (finding doc). All design sections covered; the "Explicitly out of scope" items (ATR-multiple stops, signal-cross re-entry, equity-curve basis, bot.py changes, out-of-sample validation) are correctly absent from every task.
- **No placeholders:** every step has runnable code or an exact, mechanical instruction with stated expected output. The one intentional exception — `CANDIDATE_PCT`/`CANDIDATE_COOLDOWN` in Task 3 Step 3 — is not a forbidden placeholder: it's data that provably cannot exist until Task 3 Step 2 runs the sweep and applies a fully-specified selection formula (not a vague "TBD"), and Step 4 explicitly verifies the values were substituted before the expensive rolling run proceeds.
- **Type/name consistency:** `trailing_stop_pct`, `trailing_stop_cooldown_days`, `_apply_trailing_stop(self, df)` used identically across Task 1's two edits. Task 2/3's scripts import `SMATrendFollowing`, `Backtester`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` with their real, current signatures (verified by reading `backtest/strat_backtest.py` directly while writing this plan, including `RollingBacktester`'s exact `f"{strat.name} {metric_label} (%)"` column-naming convention that `summarize_rolling_results` and Task 3's segmentation code both rely on).
