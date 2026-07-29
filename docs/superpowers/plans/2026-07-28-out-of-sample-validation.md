# Out-of-Sample Overfitting Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether Table 4's mechanically-selected "Best Practice" pick (or any of its 43 sibling variants) generalizes to a genuinely unseen period, by selecting a winner using only pre-2016 window history and evaluating that frozen config on a single non-rolling 2016-to-today backtest that was never touched during selection.

**Architecture:** Add one backward-compatible parameter to `generate_signal_comparison.py`'s existing `run_variant()` so it can be pointed at a restricted date range. Write a new script, `backtest/validate_out_of_sample.py`, that reuses the existing variant-building and best-practice-picking logic unchanged, adds a calendar-cutoff date filter for the selection phase, and adds a new single-backtest evaluation path (via `Backtester` directly, not `RollingBacktester`) for the out-of-sample phase. Run it once and write up the finding as a standalone doc.

**Tech Stack:** Python 3.11, pandas — same as the rest of the project. No new dependencies.

**Full design context:** `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`

## Global Constraints

- **Cutoff is 2016-01-01.** Selection phase uses windows whose full 26-year span ends by this date (`start_date <= 1990-01-01`, given `PERIOD_YEARS=26`). Evaluation phase covers 2016-01-01 through today, single non-rolling run.
- **Reuse, don't duplicate.** `build_sma_variants()`, `build_ema_variants()`, `pick_best_practice()`, `PERIOD_YEARS`, `LEVERAGE_CONFIG` must be imported from `backtest/generate_signal_comparison.py`, not redefined. The only new logic is date filtering and the single-backtest evaluation path.
- **`period_years` for the evaluation phase must be computed dynamically** as `int((pd.Timestamp.today() - CUTOFF).days / 365.25)` — **floored to a whole integer**, never hardcoded and never left as a fractional float. `Backtester.__init__` computes `end_dt = start_dt + pd.DateOffset(years=period_years)`, and `pd.DateOffset` raises `ValueError: Non-integer years and months are ambiguous` for a non-whole `years=` value (discovered during Task 2's implementation — the original design's un-floored division is a plan bug, not an implementer error). Flooring means the evaluation window is very slightly shorter than the absolute maximum available (loses a few months, not years) — acceptable, and this stays comfortably within `Backtester.run()`'s 98%-span window-length-validation check (added in a prior plan) since the sliced data will closely match the (now slightly shorter) requested span. Do not "fix" this by rounding up or by modifying `Backtester.__init__` — rounding up would push `requested_span_days` past what real data can fill, and modifying `Backtester.__init__` is an engine change outside this plan's scope.
- **No change to Table 4's published numbers, the Best Practice pick, `bot.py`, or any strategy logic.** This is a new, separate research script — read-only with respect to everything already published.

---

### Task 1: Add an optional `start_dates` override to `run_variant()`

**Files:**
- Modify: `backtest/generate_signal_comparison.py:61-91` (`run_variant` function)

**Interfaces:**
- Produces: `run_variant(variant, start_dates=None)` — when `start_dates` is `None` (every existing call site), behavior is byte-identical to today. When a `pd.DatetimeIndex` is passed, it's used directly instead of the internally-computed full candidate range.

- [ ] **Step 1: Capture a baseline BEFORE changing any code**

```bash
python -c "
from backtest.generate_signal_comparison import build_sma_variants, run_variant
v = build_sma_variants()[0]
row = run_variant(v)
print('row:', {k: v for k, v in row.items() if k != 'Strategy'})
"
```
Record the exact printed output.

- [ ] **Step 2: Change the function signature and body**

Replace `backtest/generate_signal_comparison.py:61-65`:
```python
def run_variant(variant):
    strat = variant["strategy"]
    signal_ticker = variant["signal_ticker"]
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
```
with:
```python
def run_variant(variant, start_dates=None):
    strat = variant["strategy"]
    signal_ticker = variant["signal_ticker"]
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    if start_dates is None:
        start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
```

- [ ] **Step 3: Re-run the exact same baseline command and diff**

```bash
python -c "
from backtest.generate_signal_comparison import build_sma_variants, run_variant
v = build_sma_variants()[0]
row = run_variant(v)
print('row:', {k: v for k, v in row.items() if k != 'Strategy'})
"
```
Expected: identical output to Step 1 — proves the default (no-override) path is unaffected.

- [ ] **Step 4: Confirm the override actually takes effect**

```bash
python -c "
import pandas as pd
from backtest.generate_signal_comparison import build_sma_variants, run_variant
v = build_sma_variants()[0]
restricted = pd.date_range('1986-04-29', '1990-01-01', freq=pd.DateOffset(months=1))
row = run_variant(v, start_dates=restricted)
print('n_windows with override:', row['n_windows'])
print('window count matches restricted date count:', row['n_windows'] <= len(restricted))
"
```
Expected: `n_windows with override` is a small number (roughly matching the ~44-entry restricted range, possibly fewer if any candidate dates predate real data — should not be close to the full ~172-window default), confirming the override actually narrowed the window set rather than being silently ignored.

- [ ] **Step 5: Commit**

```bash
git add backtest/generate_signal_comparison.py
git commit -m "feat: add optional start_dates override to run_variant() for out-of-sample validation"
```

---

### Task 2: Write `backtest/validate_out_of_sample.py`

**Files:**
- Create: `backtest/validate_out_of_sample.py`

**Interfaces:**
- Consumes: `Backtester`, `warmup_aware_start_dates` from `backtest.strat_backtest`; `build_sma_variants`, `build_ema_variants`, `run_variant` (with the Task 1 override), `pick_best_practice`, `PERIOD_YEARS`, `LEVERAGE_CONFIG` from `backtest.generate_signal_comparison`.
- Produces: prints a verdict (in-sample winner, its out-of-sample rank, whether the out-of-sample-best variant matches) plus two markdown tables to stdout, and writes the same content to `backtest/out_of_sample_output.md`.

- [ ] **Step 1: Write the script**

```python
"""
Tests whether Table 4's mechanically-selected "Best Practice" strategy
config generalizes to unseen data, or was curve-fit to the history it was
selected against.

Run manually:
    python backtest/validate_out_of_sample.py

Selects a winner using only pre-CUTOFF window history (26-year windows
ending by CUTOFF, so no calendar overlap with the evaluation period), then
evaluates every variant once on the untouched CUTOFF-to-today period.
Writes a report to stdout AND backtest/out_of_sample_output.md.
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester, warmup_aware_start_dates
from backtest.generate_signal_comparison import (
    build_sma_variants, build_ema_variants, run_variant, pick_best_practice,
    PERIOD_YEARS, LEVERAGE_CONFIG,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "out_of_sample_output.md"

CUTOFF = pd.Timestamp("2016-01-01")


def selection_start_dates(tickers):
    """Candidate start dates whose full PERIOD_YEARS-year window ends by
    CUTOFF — i.e. no calendar overlap with the CUTOFF-to-today evaluation
    period. Filters warmup_aware_start_dates() rather than reimplementing
    the warmup-floor logic."""
    all_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    max_start = CUTOFF - pd.DateOffset(years=PERIOD_YEARS)
    return all_dates[all_dates <= max_start]


def run_variant_selection(variant):
    """Selection-phase run: the same rolling-window sweep run_variant()
    already does, restricted to the pre-CUTOFF window set."""
    signal_ticker = variant["signal_ticker"]
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    dates = selection_start_dates(tickers)
    return run_variant(variant, start_dates=dates)


def run_variant_evaluation(variant):
    """Evaluation-phase run: a single, non-rolling backtest over the
    untouched CUTOFF-to-today period. period_years is computed dynamically
    from the actual current date — a hardcoded value that overshoots today
    would cause Backtester.run()'s window-length check to reject this
    window as "too short" (no future data exists to fill a longer request).
    """
    strat = variant["strategy"]
    signal_ticker = variant["signal_ticker"]
    # Floored to a whole integer: pd.DateOffset(years=...), used internally
    # by Backtester.__init__, raises ValueError on a fractional years value.
    # This makes the window a few months shorter than the absolute maximum
    # available — negligible for this analysis, and keeps the slice safely
    # within Backtester.run()'s 98%-span window-length-validation check.
    period_years = int((pd.Timestamp.today() - CUTOFF).days / 365.25)
    env = Backtester(
        base_ticker="^NDX",
        signal_ticker=signal_ticker,
        start_date=CUTOFF.strftime("%Y-%m-%d"),
        period_years=period_years,
        leverage=LEVERAGE_CONFIG["leverage"],
        expense_ratio=LEVERAGE_CONFIG["expense"],
        initial_fund=10000,
        apply_tax=False,
        verbose=False,
    )
    res = env.run(strat)
    if res is None:
        return None
    row = dict(variant["row"])
    row["TWR"] = res["strategy_twr"]
    row["Max DD"] = res["max_drawdown"]
    row["Trades"] = res.get("total_trades", 0)
    return row


def render_evaluation_table(title, rows, winner_row):
    rows_sorted = sorted(rows, key=lambda r: r["TWR"], reverse=True)
    lines = [f"### {title}", "",
             "| ATR | Signal | T+2 | TWR | Max DD | Trades |",
             "| :--- | :--- | :--- | ---: | ---: | ---: |"]
    for r in rows_sorted:
        marker = " **<- IN-SAMPLE WINNER**" if r is winner_row else ""
        lines.append(
            f"| {r['ATR']} | {r['Signal']} | {r['T+2']} | {r['TWR']:.2f}% "
            f"| {r['Max DD']:.2f}% | {r['Trades']:.0f} |{marker}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sma_variants = build_sma_variants()
    ema_variants = build_ema_variants()
    all_variants = [(v, "SMA") for v in sma_variants] + [(v, "EMA") for v in ema_variants]

    print(f"CUTOFF: {CUTOFF.date()} | today: {pd.Timestamp.today().date()}")
    print(f"Selection phase: {len(all_variants)} variants, windows ending by {CUTOFF.date()}...")

    selection_rows = []
    for i, (variant, family) in enumerate(all_variants, 1):
        row = run_variant_selection(variant)
        print(f"  [{i}/{len(all_variants)}] {family} {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = family
            selection_rows.append(row)

    winner, excluded_count = pick_best_practice(selection_rows)
    print(f"\nIN-SAMPLE WINNER: {winner['Strategy']} | ATR={winner['ATR']} | Signal={winner['Signal']} | T+2={winner['T+2']}")
    print(f"  Selection-phase Avg TWR: {winner['Avg TWR']:.2f}% | Worst DD: {winner['Worst DD']:.2f}%")

    print(f"\nEvaluation phase: {len(all_variants)} variants, single run {CUTOFF.date()} to today...")
    eval_rows = []
    winner_eval_row = None
    for i, (variant, family) in enumerate(all_variants, 1):
        row = run_variant_evaluation(variant)
        print(f"  [{i}/{len(all_variants)}] {family} {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = family
            eval_rows.append(row)
            is_winner = (
                family == winner["Strategy"] and row["ATR"] == winner["ATR"]
                and row["Signal"] == winner["Signal"] and row["T+2"] == winner["T+2"]
            )
            if is_winner:
                winner_eval_row = row

    eval_rows_sorted = sorted(eval_rows, key=lambda r: r["TWR"], reverse=True)
    winner_rank = next(
        (i for i, r in enumerate(eval_rows_sorted, 1) if r is winner_eval_row), None
    )
    oos_best = eval_rows_sorted[0] if eval_rows_sorted else None

    verdict_lines = [
        f"IN-SAMPLE WINNER: {winner['Strategy']} | ATR={winner['ATR']} | Signal={winner['Signal']} | T+2={winner['T+2']}",
        f"  Selection-phase (windows ending by {CUTOFF.date()}): "
        f"Avg TWR {winner['Avg TWR']:.2f}% | Worst DD {winner['Worst DD']:.2f}%",
    ]
    if winner_eval_row is not None:
        verdict_lines.append(
            f"  Out-of-sample ({CUTOFF.date()} to today): "
            f"TWR {winner_eval_row['TWR']:.2f}% | Max DD {winner_eval_row['Max DD']:.2f}% "
            f"-> rank #{winner_rank} of {len(eval_rows_sorted)}"
        )
    else:
        verdict_lines.append("  Out-of-sample: NO DATA (window rejected)")
    if oos_best is not None:
        matches = winner_eval_row is not None and oos_best is winner_eval_row
        if matches:
            verdict_lines.append("  Out-of-sample best variant MATCHES the in-sample winner.")
        else:
            verdict_lines.append(
                f"  Out-of-sample best variant DIFFERS: {oos_best['Strategy']} | ATR={oos_best['ATR']} "
                f"| Signal={oos_best['Signal']} | T+2={oos_best['T+2']} "
                f"(TWR {oos_best['TWR']:.2f}%, Max DD {oos_best['Max DD']:.2f}%)"
            )

    sma_eval = [r for r in eval_rows if r["Strategy"] == "SMA"]
    ema_eval = [r for r in eval_rows if r["Strategy"] == "EMA"]
    sma_table = render_evaluation_table("SMA — Out-of-Sample Evaluation", sma_eval, winner_eval_row)
    ema_table = render_evaluation_table("EMA — Out-of-Sample Evaluation", ema_eval, winner_eval_row)

    full_output = "\n".join(verdict_lines) + "\n\n---\n\n" + sma_table + "\n\n---\n\n" + ema_table
    print("\n" + full_output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"\nWritten to {OUTPUT_PATH}")
```

- [ ] **Step 2: Smoke-test the selection-phase date filtering before the full run**

```bash
python -c "
from backtest.validate_out_of_sample import selection_start_dates
dates = selection_start_dates(['^NDX'])
print('selection windows:', len(dates), '| range:', dates[0].date(), 'to', dates[-1].date())
dates2 = selection_start_dates(['^NDX', '^GSPC'])
print('cross-signal selection windows:', len(dates2), '| range:', dates2[0].date(), 'to', dates2[-1].date())
"
```
Expected: both print a window count in the low-to-mid 40s (given the design's ~44-window estimate — exact count depends on today's date since `warmup_aware_start_dates` computes warmup from live data, but should be well under 100 and nowhere near the full ~172-window default), with the range ending on or before `1990-01-01`. If either range extends past 1990-01-01, the filter has a bug — stop and investigate before running the full script.

- [ ] **Step 3: Smoke-test one full variant end-to-end (both phases) before the full 44-variant run**

```bash
python -c "
from backtest.generate_signal_comparison import build_sma_variants
from backtest.validate_out_of_sample import run_variant_selection, run_variant_evaluation
v = build_sma_variants()[0]
sel = run_variant_selection(v)
ev = run_variant_evaluation(v)
print('selection row:', {k: val for k, val in sel.items() if k not in ('Strategy',)})
print('evaluation row:', ev)
"
```
Expected: `selection row` prints a dict with real `Avg TWR`/`Worst DD`/etc. values and a small `n_windows` (matching Step 2's range). `evaluation row` prints a dict with real `TWR`/`Max DD`/`Trades` values, no traceback. This confirms both phases actually work before committing to the full ~10-minute-or-less run (44 variants × ~44 windows for selection is much cheaper than Table 4's original ~172-window sweep, plus 44 single-run evaluations — should be noticeably faster than Table 4's original run, but budget a few minutes).

- [ ] **Step 4: Add the scratch output file to `.gitignore`**

Append to `.gitignore`:
```
backtest/out_of_sample_output.md
```

- [ ] **Step 5: Commit**

```bash
git add backtest/validate_out_of_sample.py .gitignore
git commit -m "feat: add out-of-sample overfitting validation script"
```

---

### Task 3: Run the validation and write up the finding

**Files:**
- Modify: `docs/out-of-sample-validation-2026-07-28.md` (create — this is the doc named in the design spec)
- Modify: `docs/optimization-analysis-2026-07-27.md` (add a one-line cross-reference from §7's addendum to the new doc)

- [ ] **Step 1: Run the full validation**

```bash
python backtest/validate_out_of_sample.py
```
Expect no tracebacks, a printed verdict block, and a final "Written to backtest/out_of_sample_output.md" line. This should run noticeably faster than Table 4's original generation (smaller selection window set, and the evaluation phase is 44 single backtests rather than a rolling sweep) — but if it runs long, that's not itself a sign of a problem, just wait for it.

- [ ] **Step 2: Sanity-check the output before writing up**

Read `backtest/out_of_sample_output.md`. Confirm:
- The in-sample winner is a real, specific combination (not blank/error).
- Its selection-phase Avg TWR is in a similar ballpark to Table 4's published numbers for the same combination if it happens to match the Table 4 winner (SMA/ATR x3.0/Own/Off) — a wildly different number for an identical config run over a different (smaller) window set isn't itself wrong, but should be in the same rough range, not off by an order of magnitude.
- Both the SMA and EMA evaluation tables have plausible row counts (20 and 24 respectively, same as Table 4, assuming no windows were rejected).

If anything looks structurally broken, investigate before writing the doc — don't publish a finding built on suspect numbers.

- [ ] **Step 3: Write `docs/out-of-sample-validation-2026-07-28.md`**

Structure the doc with these sections, filling in real content from `backtest/out_of_sample_output.md`:
- **Method** — one paragraph summarizing the calendar-cutoff split (cite `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md` for full rationale, don't repeat it all).
- **Result** — the in-sample winner, its selection-phase numbers, its out-of-sample rank and numbers, and whether the out-of-sample-best variant matches or differs from the in-sample winner. State this plainly and let the numbers speak — don't editorialize beyond what the data shows.
- **Interpretation** — if the in-sample winner ranks well out-of-sample (e.g. top quartile of 44), that's evidence the pick reflects a real, generalizing edge rather than pure overfitting. If it ranks poorly, that's evidence the Table 4 grid search likely found noise. Either way, note the honest limitation: this is a single train/test split with a small selection sample (~44 overlapping windows) and a single non-rolling evaluation run — not a repeated-fold walk-forward analysis. State walk-forward analysis (Approach B from the original comparison) as the natural next step if this single split leaves open questions.
- **Limitations** — restate briefly: small selection sample, single evaluation period, doesn't address the separately-tracked window-overlap problem.

- [ ] **Step 4: Cross-reference from the optimization analysis addendum**

In `docs/optimization-analysis-2026-07-27.md`'s "## 7. Addendum (2026-07-28)" section (the overlapping-window future-work note), add one sentence at the end pointing to the new doc, e.g.: "A related but distinct question — whether Table 4's parameter selection itself overfits — is addressed separately in `docs/out-of-sample-validation-2026-07-28.md`."

- [ ] **Step 5: Commit**

```bash
git add docs/out-of-sample-validation-2026-07-28.md docs/optimization-analysis-2026-07-27.md
git commit -m "docs: add out-of-sample validation finding for Table 4's best-practice pick"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = the "reuse, don't duplicate" constraint's prerequisite (the override hook). Task 2 = the design's "Mechanism" section (selection phase, evaluation phase, dynamic `period_years`, report generation). Task 3 = the design's "Output location" section (script run + findings doc + cross-reference). All spec sections covered; nothing in the design spec lacks a corresponding task.
- **No placeholders:** every step has runnable code or an exact instruction with stated expected output; Task 3's doc-writing step names exactly which sections to write and what each should contain, sourced from the script's real output rather than invented content.
- **Type/name consistency:** `run_variant(variant, start_dates=None)`, `selection_start_dates(tickers)`, `run_variant_selection(variant)`, `run_variant_evaluation(variant)` signatures used identically across Tasks 1-2. `pick_best_practice`, `build_sma_variants`, `build_ema_variants`, `PERIOD_YEARS`, `LEVERAGE_CONFIG`, `warmup_aware_start_dates`, `Backtester` all imported with their real, current signatures (verified by reading `backtest/generate_signal_comparison.py` and `backtest/strat_backtest.py` directly while writing this plan).
