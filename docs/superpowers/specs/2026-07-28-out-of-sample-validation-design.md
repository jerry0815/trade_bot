# Out-of-Sample Validation Design

**Status:** Approved by user 2026-07-28. Ready for implementation planning.

## Problem

Table 4 (`README.md`) picks a "best real-world practice" strategy configuration
by grid-searching 44 SMA/EMA parameter combinations against one rolling-window
backtest history and taking the highest average TWR (after excluding the worst
drawdown quartile). The final whole-branch review that shipped Table 4 already
flagged this as a possible overfitting risk: the winning ATR value (x3.0) sits
in the middle of a non-monotonic sweep (16.46% → 22.05% → 23.53% → **24.53%** →
23.40% across x1.5/x2.0/x2.5/x3.0/x3.5), which is a classic symptom of a
parameter search finding noise rather than a robust optimum.

Separately, `warmup_aware_start_dates()` steps candidate window starts
**monthly** over **26-year** windows, so adjacent windows share nearly all
their history — the ~172-193 windows per table are not independent samples.
That overlap problem (tracked as future work in
`docs/optimization-analysis-2026-07-27.md` §7) and the overfitting problem are
related but distinct:

- **Overlap** is about whether the *reported statistics* (avg/median TWR) are
  honest given how correlated the underlying samples are.
- **Overfitting** is about whether the *selection process itself* (grid-search
  44 variants, pick the max) found a real edge or just curve-fit to this one
  particular history.

This design addresses **overfitting only** — the user's stated priority. The
overlap problem remains separately deferred.

## Goal

Determine whether Table 4's mechanically-selected "Best Practice" pick (SMA,
ATR x3.0, own ^NDX signal, T+2 off) — or any of the other 43 variants — holds
up when its parameters are chosen using only older market history, then
evaluated on a later, disjoint period never used during selection.

## Why not the obvious "split by window start date" approach

The first design considered splitting the existing rolling-window set by
*start date* (e.g. train on windows starting 1986-1993, test on windows
starting 1994-2000). This was rejected: every window is 26 years long, so a
window starting 1990 (ending 2016) and a window starting 1996 (ending 2022)
share 20 years of the same underlying calendar history. Splitting by start
date does not produce a leak-free train/test split — the "test" windows would
still be evaluated substantially on data the "training" windows already
selected against.

## Mechanism: split by calendar time, not window start date

**Cutoff: 2016-01-01.**

- **Selection phase:** restrict the candidate window set to windows whose full
  26-year span *ends by* the cutoff — i.e. `start_date <= cutoff - 26 years`
  = `start_date <= 1990-01-01`. Combined with the existing warmup floor
  (`^NDX`'s real data + 210 days ≈ 1986-04-29), this gives a selection window
  range of **1986-04-29 to 1990-01-01** (~44 monthly-stepped windows). Every
  one of these windows' 26-year span fully contains the dot-com bust
  (2000-2002) and the 2008 financial crisis — not a trivial selection era.
- **Evaluation phase:** the remaining, entirely untouched **2016-01-01 through
  2026-01-01** (10 years, floored to a whole integer from the actual elapsed
  time as of the run date — `pd.DateOffset(years=...)` rejects fractional
  values, so this drops roughly the most recent 7 months of 2026 data from
  the evaluation) — one single, non-rolling backtest period. This window was
  never part of *this script's own* selection-phase window set, so there is
  no calendar overlap with *that* selection sample. (It is, however, **not**
  disjoint from Table 4's own original 172-window selection sample — most of
  those windows extend past 2016-01-01 — so this evaluation period only
  yields a genuine out-of-sample result for variants selected using windows
  that end by 2016-01-01, not for Table 4's own published pick; see
  `docs/out-of-sample-validation-2026-07-28.md` for the full discussion.) It
  happens to contain the COVID crash (2020) and the 2022 rate-shock bear,
  neither of which the pre-2016-restricted selection phase ever saw — a
  meaningfully different regime, not a cherry-picked easy one.

**Trade-off accepted:** the selection sample shrinks from ~172 (heavily
overlapping) windows to ~44 (still overlapping among themselves, but that's
the separately-tracked overlap problem, not this design's concern), and the
evaluation side is a single run rather than a rolling sweep — a much blunter
signal than Table 4's existing tables. This is the accepted cost of a
genuinely leak-free test.

## Components

### 1. Selection-phase sweep (reuses existing code, no new logic)

Run the exact same 44 variants Table 4 uses — imported directly from
`backtest/generate_signal_comparison.py`'s `build_sma_variants()` /
`build_ema_variants()`, not redefined — via `run_experiment_suite()`, with
`start_dates` filtered to `warmup_aware_start_dates(...)` entries where
`date <= pd.Timestamp("2016-01-01") - pd.DateOffset(years=26)`. Apply the
existing `pick_best_practice()` logic (also imported, not reimplemented) to
get the frozen in-sample winner.

### 2. Evaluation-phase single backtest

For **all 44 variants** (not just the winner, so the full in-sample vs.
out-of-sample picture is visible, not just one data point), run a single
`Backtester` (not `RollingBacktester`) starting `2016-01-01`.

**Critical implementation detail:** `period_years` for this single window
must be computed **dynamically** at runtime as
`int((pd.Timestamp.today() - pd.Timestamp("2016-01-01")).days / 365.25)` —
**floored to a whole integer**, not hardcoded and not left fractional.
Two separate constraints force this: `Backtester.run()` (per the
window-length-validation fix from the prior backtest-refresh plan) rejects
any window whose actual data span falls short of 98% of the requested
`period_years` — a hardcoded, slightly-too-long `period_years` would cause
this exact evaluation window to be silently rejected as "too short" every
time, since there is no future data to fill a requested span past today.
And separately (discovered during implementation), `Backtester.__init__`
computes `end_dt` via `pd.DateOffset(years=period_years)`, which raises
`ValueError` on a non-whole `years=` value — the flooring resolves both
constraints at once, at the cost of the evaluation window being a few
months shorter than the absolute maximum available, which is immaterial to
this analysis.

### 3. Report generation

A new script, `backtest/validate_out_of_sample.py`, orchestrates both phases
and prints/writes:

- The in-sample winner (strategy config + its selection-phase Avg/Med/Worst
  TWR and Worst DD, using the same `summarize_rolling_results()` used
  elsewhere).
- A single table of all 44 variants' out-of-sample results (TWR, Max
  Drawdown, Total Trades — singular values, since this is one run per
  variant, not a rolling sweep — so column names differ from the
  Avg/Med/Worst convention used elsewhere), sorted by out-of-sample TWR
  descending, with the in-sample winner's row flagged.
- A short computed verdict: what rank does the in-sample winner hold
  out-of-sample (e.g. "#3 of 44"), and does the out-of-sample-best variant
  match the in-sample winner or differ (naming both if they differ).

## Output location

- New script: `backtest/validate_out_of_sample.py` (follows the existing
  `generate_readme_tables.py` / `generate_signal_comparison.py` pattern —
  runnable standalone, writes a scratch markdown file, gitignored).
- New scratch output: `backtest/out_of_sample_output.md` (gitignored, added
  to `.gitignore` alongside the existing two).
- New standalone doc: `docs/out-of-sample-validation-2026-07-28.md` — this is
  a one-off research finding, not a routine data table, so it stays out of
  README rather than becoming a 5th table. It should state the method, the
  cutoff rationale, and the actual result once the script is run, in the
  same evidence-cited style as the optimization-analysis addendum.

## Explicitly out of scope

- The overlap/independence problem (regime segmentation, block bootstrap) —
  separately tracked in `docs/optimization-analysis-2026-07-27.md` §7.
- Walk-forward analysis with multiple rolling train/test splits (the
  natural next step if this single-split result raises further questions) —
  not this pass.
- Combinatorial Purged Cross-Validation — considered and explicitly rejected
  as disproportionate machinery for this project's scale.
- Any change to Table 4's published numbers or "Best Practice" pick — this
  is a new, separate analysis, not a correction to existing published work.
- Any change to `bot.py` or live trading behavior — this is research only.

## Testing

No project test suite exists yet (tracked separately). Verification for this
script follows the project's established pattern: a smoke test on a reduced
combination set before the full run, plus manual sanity checks on window
counts/date ranges against independently-computed expected values (same
approach used for every prior `generate_*` script in this project).
