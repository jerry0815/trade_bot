# Session Handover — 2026-08-01

Written because the originating session is near its context limit. This
document is the single entry point for continuing this work in a fresh
session — read this first, then dip into the referenced files/docs as
needed rather than re-deriving context from git log.

## Repo state right now

**Pushed and clean:** `origin/main` == local `main` == commit `d3b952a`
("feat: add dual-signal agreement strategy, replace Table 4 with signal
comparison"). Everything through the dual-signal-agreement work (see
Phase 3 below) is committed and pushed.

**Uncommitted in the working tree** (from the most recent exploratory
phase, Phase 5 below — deliberately not committed yet, see "What to do
with the uncommitted work" at the end):
- `backtest/strat_backtest.py` — modified, +84/-5 lines. Adds four new
  **opt-in, byte-identical-when-unset** additions on top of the committed
  `d3b952a` state:
  - `Backtester._run_portfolio_math()` now also returns `"equity_curve"`
    (a `pd.Series` of daily portfolio value) in its result dict — purely
    additive, verified to exactly reproduce the pre-existing `max_drawdown`
    scalar before being used for anything.
  - `SMATrendFollowing` gained three new optional constructor params, all
    default `None`/off and verified not to change behavior when unset:
    `vix_threshold` (bypass T+2 confirmation on high-VIX days),
    `atr_spike_multiplier` + `atr_spike_lookback` (same bypass idea, keyed
    to realized ATR-based volatility instead of VIX — has full history
    coverage, no 1990 floor), and `sma_slope_lookback` (require the SMA to
    be rising before a re-entry counts, only affects entries not exits).
- `backtest/bootstrap_tail_risk.py` — new, untracked. Stationary-bootstrap
  tail-risk simulation (see Phase 4).
- `backtest/event_leverage_comparison.py` — new, untracked. Event-relative
  decline comparison across tickers/leverage/strategy variants (see
  Phase 5-7); already includes a VIX-adaptive column from the last time it
  was run.
- `backtest/event_leverage_output.md` — new, untracked, **not yet added to
  `.gitignore`** (the other scratch output files — `readme_tables_output.md`,
  `signal_comparison_output.md`, `out_of_sample_output.md`,
  `signal_hybrid_output.md` — all are; this one was missed).

Run `git status` / `git diff backtest/strat_backtest.py` on resume to see
the exact current diff before deciding what to do with it.

## What this project is

A trend-following trading bot (`bot.py`, run daily via
`.github/workflows/daily_check.yaml`) that decides whether to hold TQQQ
(3x NDX) or move to cash/defensive assets, based on an SMA200+ATR band
signal. `backtest/strat_backtest.py` is the whole backtest engine.
`README.md` documents the strategy and carries the project's published,
reviewed backtest tables. `bot.py`'s actual live config as of this session:
`SMATrendFollowing(sma_window=200, t2_confirmation=True)` (default
`atr_multiplier=2.5`), with its `RECOMMENDED ACTION` driven by the
**S&P 500 signal** (`bot.py:78`, `stats_sp500['action']`) — not NDX's own
signal, a point that tripped up an early analysis this session (see
Phase 2).

**Standing methodology convention** used everywhere in this project:
rolling 26-year backtests, monthly-stepped start dates from
`warmup_aware_start_dates()` (ticker's real data start + 210 days warmup),
run via `run_experiment_suite()`/`RollingBacktester`, summarized via
`summarize_rolling_results()`. All three are in `strat_backtest.py` and
reused by every generator script — don't reimplement this logic.

**Known, already-flagged limitation** that colors everything: the ~172
rolling windows are heavily overlapping (adjacent windows share 25 years
11 months of history), so "172 windows" overstates independent evidence.
Documented in `docs/optimization-analysis-2026-07-27.md` §7. Relevant any
time a rolling-window aggregate is presented as if it were 172 independent
samples.

## Phase-by-phase summary (chronological)

### Phase 1 — Backtest refresh to match bot.py's live config (committed, pushed)
README's Tables 1-3 were regenerated with `t2_confirmation=True` to match
what `bot.py` actually runs (they'd been generated without it). Along the
way, found and fixed a real engine bug: `Backtester.run()` accepted rolling
windows shorter than the requested `period_years` instead of rejecting
them (window-length-validation fix, still in `strat_backtest.py` today —
not part of the uncommitted diff). Also produced:
`docs/optimization-analysis-2026-07-27.md` (codebase audit) and
`docs/superpowers/plans/future-generalize-backtest-framework.md`
(unexecuted future refactor plan, explicitly out of scope this session).

### Phase 2 — Table 4 v1: 44-variant ATR/signal/T+2 sweep (superseded, see Phase 3)
Added `atr_multiplier`/`t2_confirmation` to `EMACrossover`, promoted
`warmup_aware_start_dates`/`summarize_rolling_results` into
`strat_backtest.py` as shared helpers, wrote
`backtest/generate_signal_comparison.py` (still present, still used by
Phase 3's `compare_signal_hybrid.py` via import). Published a first Table 4
with a mechanically-computed "Best Practice" pick. Final review caught a
real error: the published comparison benchmarked against the wrong
`bot.py` baseline (NDX-own-signal instead of the actual S&P-signal-driven
live config) — fixed before merge. This table (and its full 44-row ATR/EMA
sweep data) was later **fully replaced** by Phase 3's narrower table, per
explicit user decision after being warned about the tradeoff (the ATR
sweep / EMA comparison data is gone from README but still recoverable from
git history / `CHANGELOG.md`'s entry for it).

### Out-of-sample validation (committed, pushed) — parallel side quest
Design in `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`,
plan in `docs/superpowers/plans/2026-07-28-out-of-sample-validation.md`,
script `backtest/validate_out_of_sample.py`, finding written up in
`docs/out-of-sample-validation-2026-07-28.md`. Bottom line (corrected
during final review from an initially wrong framing): Table 4's originally-
published "Best Practice" pick was **never actually validated
out-of-sample** — its own 172-window selection sample's latest window ends
*today*, so no historical cutoff can cleanly separate "selection" from
"test" data for that specific pick. The one genuinely leak-free
out-of-sample result obtained (a different variant, selected using only
pre-2016 history) ranked #30 of 44 on the untouched 2016-2026 period — a
rank failure, not a losses story (it still beat its own in-sample average).
Walk-forward analysis was flagged as the natural rigorous next step, not
yet built.

### Phase 3 — DualSignalAgreement strategy, Table 4 v2 (committed, pushed, current README state)
User asked to compare NDX-own signal vs S&P-signal vs a new hybrid: only
flip position when both ^NDX and ^GSPC's independent SMA+ATR trend signals
agree; disagreement or either-neutral holds prior state. Implemented as
`DualSignalAgreement` in `strat_backtest.py` (this class **is** committed,
unlike the Phase 5-7 additions below). Script:
`backtest/compare_signal_hybrid.py`. Finding: dual-signal agreement with
T+2 **off** beat both single-signal setups on every return metric with the
fewest trades (25.81% Avg TWR, 9 trades, vs 23.53%/23.56% and 12-15 trades
for the single-signal baselines). Per explicit user decision, this became
the new (and current) Table 4 in README, replacing Phase 2's sweep table
entirely. `README.md`'s current Table 4 section and `CHANGELOG.md` both
carry an explicit caveat that this had lighter review than the rest of the
document (verified via cross-validation against Table 1/3's already-
published numbers, but the dual-signal logic itself wasn't through a full
multi-round adversarial review).

### Phase 4 — Deep risk analysis, mostly exploratory / not committed
A long interactive sequence answering direct questions about strategy risk,
not part of any formal plan:
- Worst-10 rolling windows for `bot.py`'s live SMA config — all 10 land in
  1999-2000 (windows launched right into the dot-com top). No file
  artifact, ad-hoc lookup.
- Added `equity_curve` to `Backtester`'s result dict (now in the
  uncommitted diff) to support drawdown-episode analysis: a single
  1999-2025 run's equity curve, broken into distinct peak-to-trough
  episodes. Finding: the worst episode (dot-com, -83.39%) took **~13.5
  years** to recover (peak 2000-03-27, new high not until 2013-09-17) —
  every other crisis recovered in under 2 years. 2008 doesn't show up as
  its own episode because the strategy exited early (2008-01-08) and the
  portfolio was already underwater from dot-com the whole time, so 2008's
  local dip never set a new low within that still-open episode.
- Event-relative analysis (isolating each of 5 known crises' effect from
  running-peak "absorption" into other events) — the methodology used
  throughout the rest of this phase and Phases 6-7. Script:
  `backtest/event_leverage_comparison.py` (uncommitted). The 5 reference
  crisis windows used everywhere below:
  ```python
  EVENTS = [
      ("Black Monday 1987",    "1987-08-25", "1987-12-04"),
      ("Dot-com crash",        "2000-03-24", "2002-10-09"),
      ("2008 GFC",             "2007-10-09", "2009-03-09"),
      ("COVID crash",          "2020-02-19", "2020-03-23"),
      ("2022 rate-shock bear", "2022-01-03", "2022-10-12"),
  ]
  ```
  Result at 3x/^NDX: 2008 is the strategy's best relative case (-31.77% vs
  -94.57% buy&hold, only 17.4% in-market); COVID is its worst relative case
  (-69.61% vs -69.96% buy&hold, 83.3% in-market — the trend filter barely
  reacted because COVID's crash was too fast, ~5 weeks). Extended to a
  30-row table across {QQQ/^NDX, S&P500/^GSPC} × {1x, 2x, 3x} × strategy vs
  buy&hold — protection was positive in all 30 rows, 2008 best everywhere,
  COVID and Black Monday consistently weakest everywhere. (Caught and fixed
  a sign-inversion bug in the "Protection" column before presenting this —
  worth remembering as a caution for anyone re-deriving these numbers.)
- Block-bootstrap tail-risk simulation:
  `backtest/bootstrap_tail_risk.py` (uncommitted). First version (fixed
  60-day blocks) was **badly biased** — quantified and confirmed: with 110
  blocks/path and crash-days at 12.8% of history, each synthetic path drew
  ~14 crisis-touching blocks on average, when real 26-year windows only
  ever contain 2-4. Corrected with a **stationary bootstrap** (geometric
  block lengths), calibrated so expected crisis-touching-blocks-per-path
  matches real history (~3): converged on expected block length ~1500
  trading days (~6 years). Corrected finding: median simulated 26-year max
  drawdown -83.51% (close to the real historical worst, -84.99% — meaning
  that real worst case looks like a *typical* outcome once crisis frequency
  is properly calibrated, not a freak extreme), and 41.8% of simulated
  paths are worse than anything that's actually happened in 40 years of
  real data.

### Phase 5 — VIX-adaptive T+2 (uncommitted, `vix_threshold` param)
Idea: bypass T+2 confirmation (act same-day instead of waiting 2 days) on
days where VIX is elevated, since a genuine fast crash's direction isn't
ambiguous — confirmation delay costs more than it filters. Implemented as
`vix_threshold` on `SMATrendFollowing`. Tested at 25/30/35 — **stable
across all three** (a good sign, unlike Phase 6 below): COVID improves
substantially everywhere (+9.5pp to +21.6pp across all 6 ticker/leverage
combos tested), 2008/dot-com/Black-Monday completely untouched (`+0.00`
exactly, every combo — Black Monday because VIX data doesn't exist before
1990), small consistent cost at 2022 (-0.07pp to -1.64pp). VIX>30 was the
best single threshold (full-history: TWR 16.99%→19.32%, Worst DD unchanged
at -83.39%, trade count unchanged at 11).

**Then the user asked the right skeptical question**: is this actually
COVID-specific? Segmented the full 172-window rolling set into
COVID-containing (start ≥ 1994, 79 windows) vs not (93 windows):
COVID-containing windows improve +3.04pp avg TWR; non-COVID windows
improve only +0.11pp — **essentially all the aggregate benefit is COVID-
specific**. Conclusion as currently stated to the user: real, consistent,
not a bug — but resting almost entirely on one historical event recurring.
Not committed; not currently recommended as a `bot.py` change without
more validation.

### Phase 6 — ATR-spike bypass, attempted extension to pre-1990 (uncommitted, `atr_spike_multiplier`/`atr_spike_lookback`)
Motivation: VIX can't help Black Monday 1987 (no data before 1990) or any
pre-1990 event. Built an alternative bypass keyed to realized volatility
(`ATR / Close`, relative to its own 60-day trailing average) instead of
VIX — has full history coverage. Checked first whether this was even
plausible: confirmed empirically that ATR was already climbing in the days
*before* Black Monday itself (Oct 14-16, 1987 — already ~1.76x its 60-day
baseline by the Friday before the Monday crash), so not purely reactive.

**Result was a red flag, not a green light:** at multiplier 1.5, Black
Monday improved dramatically (-65.91% → -37.67%, the single biggest win of
anything tested this session) — but at 1.75 and 2.0, the effect
**completely disappeared**, back to exactly baseline. That's the same
"sharp non-monotonic cliff between adjacent parameter values" pattern this
project has already flagged twice (Table 4's ATR sweep) as an overfitting
signature. Decision (with user): **do not pursue this further** — the VIX
data limitation for pre-1990 events is being accepted as a known, honestly-
documented gap rather than patched with a fragile fix. User also asked
whether a pre-1990 VIX-equivalent index could be sourced — answer: no,
CBOE's own official VIX starts exactly at 1990 (nothing else exists via
this project's data sources without introducing an unvalidated external
source).

### Phase 7 — SMA-slope re-entry filter (uncommitted, `sma_slope_lookback`), hypothesis rejected
Motivation: dot-com's -83% local decline was assumed to be a whipsaw
problem (repeated false re-entries during a grinding, multi-year bear with
bear-market rallies). Built a filter requiring the SMA itself to be rising
before a re-entry counts (only gates entries, not exits). **Result: zero
effect on every single event tested, including dot-com** (`-83.25%`
identical at every lookback: 10/20/40 days), and the full-history aggregate
got strictly *worse* (TWR down, max DD down) with **trade count completely
unchanged** at every setting — meaning the filter never actually blocked a
re-entry, it just delayed every entry's timing for no benefit.

**Investigated why by pulling the actual trade log for 1999-2003** (via
`Backtester.run()`'s already-returned `trade_log` — no new code needed):
only **2 trades total** in that whole window:
1. Entry 1999-11-12 → Exit 2000-10-12 (335 days) → **-36.75%**
2. Entry 2003-05-01 → Exit 2004-08-10 (467 days) → +29.90%

**This overturned the whole premise.** Dot-com wasn't a whipsaw problem at
all — the strategy entered once before the top, correctly stayed in cash
for 2.5 years, and re-entered once cleanly at the real recovery. The -83%
local decline came from **one held position where the trend-following exit
signal was too slow to react** to a severe intra-trade decline (335 days
held before the SMA+ATR+T+2 signal finally confirmed the exit) — an
exit-speed problem on an open position, not a re-entry/whipsaw problem. A
re-entry filter was solving a problem that didn't exist.

## Immediate next step (in progress when context ran out)

The reframed hypothesis: dot-com needs a mechanism to protect an
**already-open position** independent of the slow trend signal — most
directly, a **trailing stop-loss** (exit if price falls some % from its own
peak since entry, regardless of what the SMA/ATR band currently says).
This is conceptually different from everything tried in Phases 5-7 (those
all only affect signal *confirmation speed*; a trailing stop is open-
position risk management).

**Last thing in flight, not yet done:** was about to pull NDX's actual
intraday/daily price path during the Nov-1999-to-Oct-2000 hold (trade #1
above) to see how deep it actually got and how early a trailing stop could
plausibly have caught it, before designing/implementing the mechanism. This
is the natural resume point.

## What to do with the uncommitted work

Three experimental `SMATrendFollowing` params (`vix_threshold`,
`atr_spike_multiplier`+`atr_spike_lookback`, `sma_slope_lookback`) plus the
`equity_curve` field are sitting uncommitted in `strat_backtest.py`, along
with two new analysis scripts. None of these are recommended for adoption
into `bot.py` as of this handover:
- `vix_threshold` — real, consistent effect, but demonstrated to be ~COVID-
  specific when properly segmented; not validated further (no rolling-
  window out-of-sample check attempted).
- `atr_spike_multiplier` — explicitly rejected as too fragile (parameter
  cliff at 1.5→1.75).
- `sma_slope_lookback` — hypothesis it was built to test was disproven;
  net negative in every measurement taken.

Recommend, on resume: either (a) commit these as clearly-labeled
"experimental, not adopted" additions (they're all byte-identical-when-off
so carry zero risk to existing behavior) so the exploration isn't lost, or
(b) if the trailing-stop idea supersedes `sma_slope_lookback` entirely,
consider removing that one param before committing rather than carrying
dead experimental code forward. Either way, add
`backtest/event_leverage_output.md` to `.gitignore` (matches the existing
pattern for the other four scratch output files) before committing.
