# Trailing-Stop Out-of-Sample Validation Design

**Status:** Approved by user 2026-08-02. Ready for implementation planning.

## Problem

`docs/trailing-stop-loss-finding-2026-08-01.md` validated a trailing-stop
candidate (`trailing_stop_pct=0.08`, `trailing_stop_cooldown_days=60`) on
the full 172-window rolling aggregate: it improves every metric over
baseline (Avg TWR 21.77%→23.43%, Worst DD -83.40%→-64.78%), survives an
event-relative sweep across 5 crises, and passed a fragility check that
rejected a cliff-prone alternative. But — as that doc's own Verdict section
states — the whole pipeline (sweep, selection, rolling validation) ran
against one overlapping in-sample window set, with no train/test split.

This project has already run exactly this kind of check once before, for
a different mechanically-selected configuration (Table 4's SMA/EMA sweep):
`docs/out-of-sample-validation-2026-07-28.md` found that pick ranked only
**#30 of 44** when evaluated on a genuinely held-out period, despite
looking strong on the same kind of full-history rolling aggregate. That is
the direct, concrete reason this step cannot be skipped before recommending
the trailing-stop for `bot.py`.

## Goal

Determine whether a trailing-stop candidate selected using only pre-2016
window history — and separately, today's already-published `(8%, 60d)`
pick — hold up when evaluated on the untouched 2016-today period never
used during selection.

## Mechanism: reuse the existing calendar-cutoff design, adapted

Same split as `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`:
**cutoff `2016-01-01`.** Selection uses rolling windows whose full 26-year
span ends by the cutoff (`start_date <= 1990-01-01`, ~44 windows via
`warmup_aware_start_dates`); evaluation uses a single non-rolling backtest
over the untouched `2016-01-01`-to-today period.

This cutoff has a property specific to the trailing-stop investigation:
of the 5 crises tracked throughout this project (Black Monday 1987,
dot-com 2000, 2008 GFC, COVID 2020, 2022 rate-shock bear), the first three
fall entirely before 2016 and the last two entirely after — so this split
also happens to separate "the crises the mechanism was evaluated against"
from crises it has never been tuned against, without any extra machinery.

### Selection-phase metric: rolling Avg TWR improvement (not event-relative decline)

Two methodologies were considered:
- **Rolling Avg TWR improvement** (chosen): sweep all 28 `(pct, cooldown)`
  combinations' rolling-aggregate Avg TWR on the ~44 pre-2016 windows,
  same machinery `backtest/trailing_stop_validate.py` already uses.
  Matches Table 4's already-validated out-of-sample methodology exactly.
- **Event-relative decline on the 3 pre-2016 crises only**: mirrors how
  the current `(8%, 60d)` candidate was *actually* chosen in the original
  Task 3 (event-relative sweep via `backtest/trailing_stop_sweep.py`),
  restricted to Black Monday/dot-com/GFC. More faithful to the original
  selection process, but a less-precedented methodology for an
  out-of-sample check specifically.

User selected rolling Avg TWR improvement: more rigorous, more consistent
with this project's established precedent.

### Candidate selection procedure (selection phase)

1. Run baseline + all 28 combinations through `RollingBacktester` /
   `run_experiment_suite`, restricted to `warmup_aware_start_dates(...)`
   entries where `date <= 1990-01-01`.
2. Compute `improvement = candidate Avg TWR - baseline Avg TWR`, all
   measured on this restricted ~44-window set (not the full 172).
3. **Shortlist**: candidates whose improvement clears a minimum bar.
4. **Non-fragility judgment** (not a rigid re-derived numeric cliff
   threshold): among shortlisted candidates, prefer ones whose immediate
   grid-neighbors (adjacent `pct` at the same `cooldown`, adjacent
   `cooldown` at the same `pct`) show improvement of the same order of
   magnitude, not a double-digit-multiple cliff — the same principle
   applied in Task 3, deliberately not hard-coded to a specific ratio this
   time. Task 3's own history is the reason: a purely mechanical
   `>= 1.0pp` neighbor floor let an 8.6x cliff through once already, on a
   different improvement scale (event-relative pp, typically 1-60) than
   this phase's (rolling Avg TWR pp, likely much smaller in magnitude —
   the full-history check found only +1.66pp for the eventual winner).
   Report the full shortlist and reasoning explicitly rather than
   asserting a single formula covers it.
5. Record the selected `(pct, cooldown)` — or explicitly record "no
   candidate clearly stands out" as a valid outcome, same as the original
   Task 3's contingency.

### Evaluation phase

A single `Backtester` run (not rolling) per variant — baseline + all 28
combinations, 29 total — for `start_date=2016-01-01`, with `period_years`
computed dynamically as `int((pd.Timestamp.today() - CUTOFF).days / 365.25)`,
**floored to a whole integer** (same established requirement from
`docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`,
re-derived there from `Backtester`'s window-length-validation and
`pd.DateOffset`'s fractional-years `ValueError` — do not re-litigate,
just reuse). `base_ticker="^NDX"`, `signal_ticker="^GSPC"`, `leverage=3`,
`expense_ratio=0.0095` — same config used throughout this investigation.

Report all 29 variants' evaluation-phase TWR/Max DD/Trades, sorted by TWR
descending, with two rows flagged explicitly (they may or may not be the
same row):
- The pre-2016-selection-phase winner.
- Today's already-published `(8%, 60d)` pick (selected using the full,
  un-split history) — included regardless of whether the selection phase
  picks it again, since its out-of-sample rank is the more directly
  decision-relevant number for the adoption question this whole
  investigation is building toward.

## Components

### 1. New script: `backtest/trailing_stop_out_of_sample.py`

Follows `backtest/validate_out_of_sample.py`'s structure (selection-phase
sweep with a date-filtered window set, evaluation-phase single-backtest
loop, verdict + two markdown tables, prints and writes to a gitignored
scratch file) — reusing that file's dynamic-`period_years` handling
directly rather than re-deriving it. Imports `SMATrendFollowing`,
`Backtester`, `RollingBacktester`, `run_experiment_suite`,
`warmup_aware_start_dates`, `summarize_rolling_results` from
`backtest.strat_backtest` — no new engine logic, this is orchestration
only, matching every prior analysis script in this project.

### 2. Finding write-up: `docs/trailing-stop-loss-out-of-sample-2026-08-02.md`

States the method (citing this spec for full rationale), the selection
outcome (which combination, and the fragility reasoning), the evaluation
ranking for both flagged rows, and an honest verdict: does the candidate
generalize, rank poorly (the Table 4 precedent), or land somewhere
in between — driven by the actual numbers once run, not decided in
advance.

## Explicitly out of scope

- The commission/slippage sensitivity check (raised separately in
  conversation) — a distinct follow-up, not folded into this pass.
- Any change to `bot.py`, live trading behavior, or `README.md`.
- Re-deriving the dynamic-`period_years` / window-length-validation
  mechanics from scratch — reuse `validate_out_of_sample.py`'s established,
  already-debugged handling verbatim.
- A second out-of-sample cutoff or walk-forward analysis with multiple
  splits — single-split check only, same scope discipline as the Table 4
  precedent.

## Testing

No project test suite exists (tracked separately, same as every prior
analysis script). Verification follows the established pattern: a smoke
test on a reduced combination set before the full 29-variant evaluation
run, plus a manual sanity check that the selection-phase window count is
in the same ~44-window ballpark as Table 4's original out-of-sample check
(exact count will differ slightly since `warmup_aware_start_dates` depends
on today's date).
