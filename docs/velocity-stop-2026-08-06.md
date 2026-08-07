# Velocity (Fixed-Window) Stop vs. Peak-Based Stop (2026-08-06)

## Question

The published trailing stop (`docs/trailing-stop-*` chain) anchors to the
**running peak since entry** — it can take a long time to fire against a
slow, grinding bear because the peak keeps resetting only when price makes
new highs, and the decline is measured from a moving reference that may be
old. Does a stop anchored to a **fixed trailing window** instead ("has price
fallen `pct%` within the last `window` days?") catch fast, "crazy" crashes
better, and does it reduce whipsaw — fewer stop-outs, not more — relative to
the peak stop? Or does a tighter, faster-firing trigger leak on slower bears
and/or cost more in trading?

## Method

New `_apply_velocity_stop` method on the strategy classes
(`backtest/strat_backtest.py`), added as a separate, mutually-exclusive
method from the existing peak-based `_apply_trailing_stop` (Option A: no
change to the peak stop's tested code path). Two modes, both lookahead-free
by construction (every read uses `close[i-1]` or earlier, same lag
convention as the peak stop):

- **`rolling_max`** — breach when the lagged close is `pct` below the
  **max** lagged close over the trailing `window` trading days.
- **`point_to_point`** — breach when the lagged close is `pct` below the
  lagged close from exactly `window` trading days earlier.

Both track the unleveraged **^GSPC** reference (same choice the peak stop
made, and re-confirmed as the better tracking ticker in
`docs/trailing-stop-dual-signal-2026-08-03.md`), apply the same cooldown and
trend-exit-wins precedence as the peak stop, and never trigger on the entry
day itself. Unit-tested and hand-traced for lookahead-freedom; not yet
through the multi-round adversarial review the `docs/trailing-stop-*` chain
had.

**Selection:** `backtest/velocity_stop_sweep.py` ran a 72-variant grid
(mode x window {20,30,60}d x pct {6,8,10,12}% x cooldown {20,40,60}d) on
^NDX/3x with the S&P signal and T+2, ranking by average improvement (in
percentage points) over baseline no-stop event decline across five crash
events (Black Monday 1987, dot-com, 2008 GFC, COVID, 2022). Winners:

- **`rolling_max`**: 6% / 60d window / 60d cooldown (+40.65pp avg improvement)
- **`point_to_point`**: 6% / 30d window / 60d cooldown (+29.45pp avg improvement)

These were then run through two independent lenses: the per-crash
event-relative drawdown table (`backtest/crash_event_drawdown.py`, rows E/F,
also published as README Table 5) and the 172-window rolling aggregate
(`backtest/velocity_stop_sweep.py`'s rolling-evaluation mode, also published
as README Table 6).

## Result

**Crash-event lens** (dual-signal entry, event-relative peak-to-trough,
comparing against the published peak stop D: dual-signal + GSPC stop 8/60):

| Strategy | Black Monday 1987 | Dot-com crash | 2008 GFC | COVID crash | 2022 rate-shock bear |
| :--- | ---: | ---: | ---: | ---: | ---: |
| D: Dual-signal + GSPC peak stop 8/60 | -19.55% | -51.11% | -23.88% | -42.69% | -38.06% |
| E: Dual-signal + GSPC velocity 6%/60d rolling_max | -15.47% | -6.45% | -21.42% | -25.58% | -30.03% |
| F: Dual-signal + GSPC velocity 6%/30d point_to_point | -19.55% | -43.48% | -11.16% | -42.69% | -38.06% |

Both velocity variants match or beat the peak stop on all five events. The
biggest gap is dot-com (1999-2000, a slower-grinding decline than a crash):
E cuts it from -51.11% to -6.45%, F to -43.48%.

**Rolling-return lens** (172-window aggregate, `^NDX`/3x, ATR x2.5):

| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Worst DD vs Init | Avg Trades | Windows |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dual-signal agreement (no stop) | 25.81% | 26.68% | 11.68% | -84.95% | -84.95% | 9 | 172 |
| Dual-signal agreement + peak stop 8%/60d | 24.59% | 25.36% | 12.92% | -64.78% | -54.75% | 18 | 172 |
| S&P signal [T+2] + velocity rolling_max 6%/60d, 60d cooldown | 18.36% | 18.83% | 11.06% | -58.34% | -47.66% | 30 | 172 |
| Dual-signal + velocity rolling_max 6%/60d, 60d cooldown | 19.04% | 19.51% | 11.73% | -58.92% | -47.52% | 29 | 172 |
| S&P signal [T+2] + velocity point_to_point 6%/30d, 60d cooldown | 21.58% | 22.40% | 12.87% | -67.52% | -53.46% | 21 | 172 |
| Dual-signal + velocity point_to_point 6%/30d, 60d cooldown | 18.88% | 19.22% | 12.57% | -67.64% | -53.46% | 21 | 172 |

(Worst DD vs Init = deepest dip below the starting $10k; see the README methodology note. The velocity rolling_max variant posts the shallowest loss-on-principal of any setup here, -47.5%, even better than the peak stop's -54.75% — consistent with it being the most conservative, most-traded variant.)

Velocity Avg TWR clusters 18.36%-21.58%, well below the peak stop's 24.59%
and the no-stop baseline's 25.81%. Trade counts (21-30) are also *higher*
than the peak stop's 18 and far higher than no-stop's 9.

## Findings

**1. On the crash-event lens, velocity does not leak on slow bears —
disproving the a-priori concern.** The hypothesis going in was that a
fixed-window stop, tuned to react fast, would fail on slow declines like
dot-com and 2022 because the window could "roll past" the relevant peak
before the price had fully broken. That did not happen: both selected
variants match or beat the peak stop on every one of the five crash events
tested, including the two slowest (dot-com, 2022).

**2. On the rolling-return lens, velocity clearly underperforms the peak
stop, and it does not whipsaw less.** Both halves of the original question
resolve against the velocity stop's favor here: it costs materially more
return (18-22% vs. 24.59% Avg TWR) and it fires *more* often, not less
(21-30 trades vs. 18). The tighter, window-bounded trigger is not a
strictly-better replacement for the peak stop — it is a stricter one.

**3. The rolling_max window "winner" (60d) is a tie-break artifact.** In the
selection grid, windows 20d/30d/60d gave byte-identical event-decline
results at 6%/60d-cooldown (see `backtest/velocity_stop_sweep_output.md`).
This happens because the rolling max over any of those windows lands on the
same peak day in each test crash — the window length isn't discriminating
between these three values at all in this dataset. Treat "60d" as "one of
three windows that tied," not as a value the sweep meaningfully selected.

## Answer to the question asked

**Equal-or-better crash protection, at a real and larger compounding cost,
with more trades — not fewer.** The velocity stop is a more conservative
tool than the peak stop, not a strictly dominant one: it is worth
considering specifically when protection against a slow-grinding bear
(dot-com-, 2022-style) matters more than the return given up to get it, but
it is not a free upgrade and does not deliver the "fewer whipsaws" half of
the original hypothesis.

## Caveats

- Single non-OOS-validated selection run — same bar as the Table 4 caveat.
  No out-of-sample check or parameter-stability probe (the kind the peak
  stop went through in `docs/trailing-stop-loss-out-of-sample-2026-08-02.md`
  and `docs/trailing-stop-stability-probe-2026-08-03.md`) has been run for
  the velocity stop yet.
- `_apply_velocity_stop` is new code: unit-tested and hand-traced for
  lookahead-freedom, but not through the multi-round adversarial review the
  rest of this README's findings have had.
- The rolling_max 60d window is a tie-break artifact (see Finding 3), not a
  meaningfully selected parameter.
- Overlapping-window caveat applies: 172 monthly-stepped rolling windows
  share nearly all their history with their neighbors, so this is much less
  independent evidence than "172" suggests.
- Pre-tax, no commissions/slippage — same scope as the rest of this
  README's backtests.

## Follow-ups

- Out-of-sample validation of both selected velocity variants, matching the
  procedure `docs/trailing-stop-loss-out-of-sample-2026-08-02.md` ran for
  the peak stop.
- A parameter-stability probe across the velocity stop's pct/window/cooldown
  axes (the grid in `velocity_stop_sweep_output.md` shows the ranking is
  fairly steep — worth checking whether nearby variants perform similarly or
  whether 6%/60d-cooldown is a narrow peak).
- Tax-aware re-run (matching
  `docs/trailing-stop-loss-tax-aware-out-of-sample-2026-08-02.md` for the
  peak stop) — the velocity stop's higher trade count suggests tax drag
  could be even more pronounced than what `docs/taxable-account-2026-08-06.md`
  found for the peak stop.
