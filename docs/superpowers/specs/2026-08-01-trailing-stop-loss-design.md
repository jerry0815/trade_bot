# Trailing Stop-Loss (Open-Position Risk Management) Design

**Status:** Approved by user 2026-08-01. Ready for implementation planning.

## Problem

`docs/session-handover-2026-08-01.md` (Phase 4/7) established that the
strategy's worst episode — the dot-com crash, -83.39% peak-to-trough,
~13.5 years to recover — is **not** a re-entry/whipsaw problem. The trade
log for 1999-2003 shows exactly one position held through the whole decline
(entry 1999-11-12, exit 2000-10-12, 335 days), correctly preceded and
followed by correct cash periods. Phase 7's SMA-slope re-entry filter,
built on the whipsaw hypothesis, had zero effect on every event tested and
made the full-history aggregate strictly worse — confirming the hypothesis
was wrong, not just the implementation.

The real problem: once inside that one position, the SMA200+ATR+T+2 trend
signal was too slow to react to a severe *intra-trade* decline. Every
mechanism tried so far in this session (`vix_threshold`, `atr_spike_multiplier`,
`sma_slope_lookback`) only changes how fast a **signal-driven** exit
confirms — none of them add a mechanism that watches the open position's
own P&L independent of the trend signal.

## Goal

Add an **open-position trailing stop**: exit if price falls some
percentage from its own peak since entry, regardless of what the SMA/ATR
band currently says, then re-enter through normal signal logic after a
cooldown. Validate whether this actually shrinks the dot-com episode, and —
learning from Phase 5's VIX-threshold finding (a real effect that turned
out to be ~COVID-specific) — check whether the benefit generalizes or is
narrowly dot-com-specific before calling it a candidate for `bot.py`.

## Evidence motivating the mechanism

Pulled the actual equity path for the dot-com hold (script: ad-hoc, not
committed — see "Testing" below for where this gets formalized) using the
already-existing `equity_curve` field on `Backtester`'s result dict:

- Entry 1999-11-12 at equity 175,674. True peak 600,290 on 2000-03-27.
  Eventual signal-driven exit 106,946 on 2000-10-12.
- A trailing stop of **-15% to -20% from the running peak since entry**
  would have triggered **2000-01-04/05** — three months before the March
  top — at ~294-304K equity, avoiding the bulk of the later collapse.
- Measured only from the true 3/27 peak onward, the crash was fast:
  -30% by 4/3, -50% by 4/12 (about two weeks) — a peak-relative % stop
  catches most of it even at a fairly wide threshold, without needing to
  be date- or event-aware.
- **Caveat that shapes the design below:** a -15-20% dip also occurred in
  early January 2000 that then rallied to the much higher March peak. A
  naive "exit on stop, re-enter the moment the trend signal says in-market"
  rule would likely re-buy the very next day (the SMA/ATR signal never
  said "exit" — it was the stop, not the signal, that fired), making the
  stop a no-op or a whipsaw-generator rather than protection.

## Mechanism

New optional constructor params on `SMATrendFollowing`:
`trailing_stop_pct` (e.g. `0.20` for 20%) and
`trailing_stop_cooldown_days` (e.g. `20`). Both default `None`/off,
byte-identical to current behavior when unset — same convention as the
three existing experimental params (`vix_threshold`, `atr_spike_multiplier`,
`sma_slope_lookback`).

1. **Peak tracking, reset per trade.** Track the running max of the
   **signal-ticker's Close** (not the leveraged equity curve — see
   rationale below) starting from the day a position enters. The peak
   resets to that entry-day price each time a new position opens; it does
   not persist across trades or across cash periods.
2. **Trigger.** On any day Close falls below
   `running_peak * (1 - trailing_stop_pct)`, force `in_market = False`
   for that day — same same-day timing convention the existing SMA/ATR
   band check already uses (i.e. **bypasses T+2** unconditionally when a
   trailing stop fires, regardless of the `t2_confirmation` setting). The
   whole premise of this mechanism is reacting faster than the slow trend
   signal; gating it behind the same 2-day delay it exists to route
   around would defeat the purpose.
3. **Cooldown.** Once triggered, `in_market` is forced `False` for the
   next `trailing_stop_cooldown_days` trading days *regardless of what the
   SMA/ATR signal says*, even if the signal would otherwise say
   "in-market" the very next day. After the cooldown elapses, normal
   signal-driven entry logic resumes unmodified.
4. **Measurement basis: underlying signal-ticker price, not leveraged
   equity.** The existing SMA/ATR entry/exit logic already watches the
   signal ticker's unleveraged Close — using the same series keeps the
   threshold stable and comparable across leverage tiers (a 20% underlying
   move means the same thing at 1x/2x/3x) and avoids needing separate
   tuning per leverage config. The leveraged equity curve was considered
   and rejected: at 3x, a given equity-% threshold corresponds to a much
   smaller underlying move (e.g. -20% equity ≈ -7% underlying), which
   would fire far more often and carries materially higher whipsaw risk.

## Components

### 1. `SMATrendFollowing` changes (`backtest/strat_backtest.py`)

Extend `__init__` with the two new params (name string gets a
`[Trailing Stop X%, cooldown Nd]` suffix when set, following the existing
pattern for `vix_threshold` etc.). Extend `generate_signals()` (or
wherever the `in_market` column is finalized) to compute the per-trade
running peak, apply the trigger, and apply the cooldown mask. No changes
to `Backtester` or `_run_portfolio_math` — the mechanism is entirely
signal-side, same as the three existing experimental params.

### 2. Event-relative sweep script

Extend or duplicate `backtest/event_leverage_comparison.py`'s pattern:
sweep `trailing_stop_pct` × `trailing_stop_cooldown_days` at the NDX/3x
baseline (the config the dot-com evidence above was computed on), report
event-relative decline for all 5 crises per combination. Look specifically
for:

**Addendum (2026-08-01, discovered while moving to the implementation
plan):** the "Evidence" section above measured trigger points against the
*leveraged 3x equity curve*. Re-measured against the actual design basis
(underlying `^GSPC` Close, per the Measurement-basis decision below), the
dot-com hold's peak-to-trough was only **~-13%** (peak 1527.46 on
2000-03-24 → trough 1329.78) — a stop in the original 15-30% range would
**never trigger at all** in this trade; leverage was tripling the apparent
drawdown. The real trigger range on the underlying-price basis is roughly
**5-12%** (a -10% stop first fires 2000-04-14 at close 1356.56, a modest
save vs. the eventual signal-driven exit at 1329.78 — real, but far less
dramatic than the equity-curve view implied). The sweep grid is corrected
accordingly: `trailing_stop_pct ∈ {5%, 7%, 8%, 10%, 12%, 15%, 20%}` ×
`trailing_stop_cooldown_days ∈ {10, 20, 40, 60}` (28 combinations) — wide
enough to see the effect taper off past ~12-13% (expected, a hard ceiling
from this trade's actual shape, not a fragility cliff) while still
covering the range with a real effect.
- Whether dot-com's decline actually shrinks materially.
- Non-monotonic cliffs between adjacent parameter values — the same
  fragility signature Phase 6's `atr_spike_multiplier` showed (a huge win
  at 1.5x that completely vanished at 1.75x). A candidate is only worth
  carrying forward if neighboring parameter values behave similarly, not
  if one specific combination looks great in isolation.

### 3. Rolling-window validation

For the best 1-2 candidates surviving the sweep, run the full 172-window
rolling aggregate (`run_experiment_suite()` / `summarize_rolling_results()`,
the project's standing methodology — see handover doc) to check overall
Avg/Med/Worst TWR and Worst DD impact, not just the one event.

### 4. Event-specificity segmentation check

Same motivation as the check that caught `vix_threshold` being
~COVID-specific (Phase 5), but **the COVID split mechanism doesn't
transfer directly**: verified while writing the implementation plan that
all 172 rolling windows span 26 years starting between 1986-04-29 and
2000-07-28, so **every single window's span already includes 2000-2002**
— there is no "dot-com-containing vs. not" split to make; COVID (2020) is
recent enough that only newer-start windows include it, but dot-com (2000)
is old enough that it's inside all of them.

Corrected check, using the actual asymmetry Phase 4 already found (the
worst-10 rolling windows for the live SMA config all land in 1999-2000 —
i.e. windows whose *start* lands right before/at the dot-com top, where a
freshly-opened 3x position has no accumulated cushion): segment the 172
windows by **start date** into "starts 1998-01-01 through 2001-12-31"
(the zone that produces the worst historical windows) vs. all other
starts, and compare average TWR / Worst DD improvement between the two
groups. Report honestly whether the benefit concentrates in the
already-known-worst start-date band or is general — this is a finding to
surface either way, not a gate that blocks writing it up.

## Explicitly out of scope

- ATR-multiple trailing stops (volatility-scaled distance) — rejected in
  favor of fixed %, per user decision, to avoid another ATR-based knob
  after Phase 6's fragility finding.
- Re-entry via "wait for a fresh signal cross" (price must dip back below
  the band and re-cross) — rejected in favor of a fixed day-count cooldown
  for simplicity and ease of sweeping.
- Leveraged-equity-curve-based stop thresholds — rejected, see Measurement
  basis above.
- Any change to `bot.py` or live trading behavior. Per this project's
  established pattern (`vix_threshold`, `atr_spike_multiplier`,
  `sma_slope_lookback` are all still unadopted), this stays an opt-in,
  off-by-default experimental param pending validation results — adoption
  is a separate decision after the sweep/rolling/segmentation results are
  in.
- Out-of-sample validation (train/test split like
  `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`)
  — reasonable natural next step if a candidate survives the sweep and
  segmentation check, but not this pass.

## Output location

- Modified: `backtest/strat_backtest.py` (new params, byte-identical when
  unset).
- New script (name TBD at plan time, e.g.
  `backtest/trailing_stop_sweep.py`): runnable standalone, writes a
  scratch markdown output file, gitignored following the existing
  4-file pattern in `.gitignore`.
- Finding write-up: new standalone doc under `docs/`, following the
  `docs/out-of-sample-validation-2026-07-28.md` precedent — states method,
  the parameter grid, and the actual sweep/rolling/segmentation results.
  Not added to README (this is exploratory research, same status as
  Phases 5-7), unless results are strong enough that the user decides
  otherwise at that point.

## Testing

No project test suite exists yet (tracked separately, same as every prior
`generate_*`/analysis script in this project). Verification follows the
established pattern: a smoke test on a reduced parameter combination
before the full 20-combination × 5-event sweep, plus a manual check that
`trailing_stop_pct=None` (default) reproduces byte-identical output to the
current committed behavior — the same invariant already verified for
`vix_threshold`/`atr_spike_multiplier`/`sma_slope_lookback`.
