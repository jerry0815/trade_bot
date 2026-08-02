# Trailing-Stop-Loss Finding: Dot-com Crash Protection (2026-08-01)

## Method

An opt-in trailing-stop-loss overlay was added to `SMATrendFollowing`
(`trailing_stop_pct`, `trailing_stop_cooldown_days`, both default `None`/off,
byte-identical to existing behavior when unset): the strategy exits an open
position immediately (bypassing `t2_confirmation`) the day the signal
ticker's unleveraged Close falls `trailing_stop_pct` below its own running
peak since entry, then blocks signal-driven re-entry for a fixed
`trailing_stop_cooldown_days` trading days before normal SMA/ATR
trend-signal logic resumes. Full rationale for this design — including why
the stop is measured against the unleveraged signal-ticker price rather
than the leveraged equity curve, and why re-entry uses a fixed cooldown
rather than a signal-cross condition — is in
`docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md`.

## Sweep Result

`backtest/trailing_stop_sweep.py` swept `trailing_stop_pct ∈ {5%, 7%, 8%,
10%, 12%, 15%, 20%}` × `trailing_stop_cooldown_days ∈ {10, 20, 40, 60}` (28
combinations) against the live `bot.py` config (^NDX/3x, S&P-signal-driven,
SMA 200, ATR x2.5, T+2), reporting event-relative decline across 5 known
crises per combination (`backtest/trailing_stop_sweep_output.md`).

**The mechanical candidate-selection procedure (Task 3 Step 2 of
`docs/superpowers/plans/2026-08-01-trailing-stop-loss.md`) initially
selected `(pct=5%, cooldown=60d)`** — its Dot-com `Improvement (pp)` of
**+64.13** is the single highest value anywhere in the 28×5 sweep, and it
formally cleared the procedure's non-fragility bar (its pct-neighbor
`(7%, 60d)` scores +35.95pp, comfortably above the ≥1.0pp threshold).

**A human reviewer rejected this candidate anyway.** Its *cooldown*-neighbor
`(5%, 40d)` scores only **+7.44pp** — an **8.6x** drop between adjacent
cooldown values at the same 5% stop. That is the same non-monotonic-cliff
overfitting signature this project has already rejected twice: Table 4's
original ATR sweep, and Phase 6's `atr_spike_multiplier` (a huge win at
1.5x that vanished completely at 1.75x — see
`docs/session-handover-2026-08-01.md`). A single combination looking
spectacular in isolation, while its immediate neighbor collapses to a
fraction of the effect, is exactly the pattern that has twice turned out to
be curve-fitting rather than a real, robust edge in this project's history.
The naive numeric threshold in the selection procedure (≥1.0pp on at least
one neighbor) is not tight enough to catch an 8.6x cliff, so this required
a human judgment call on top of the mechanical rule, not a substitute for
one.

**The candidate actually carried forward and validated is the runner-up:
`(pct=8%, cooldown=60d)`**, Dot-com `Improvement (pp)` **+38.21** — well
below the rejected candidate's headline number, but its cooldown-neighbor
`(8%, 40d)` scores **+37.29pp**, a **1.02x** ratio: smooth, not a cliff.
This is the combination that went into
`backtest/trailing_stop_validate.py` and is reported in
`backtest/trailing_stop_validate_output.md` below.

**Effect on the other 4 events, at `(8%, 60d)`:** every other event also
improved, none worsened — no evidence of a costly whipsaw anywhere in the
5-event sweep for this specific combination:

| Event | Improvement (pp) |
| :--- | ---: |
| Black Monday 1987 | +46.36 |
| Dot-com crash | +38.21 |
| 2008 GFC | +2.11 |
| COVID crash | +38.83 |
| 2022 rate-shock bear | +21.65 |

## Rolling-Window Result

`backtest/trailing_stop_validate.py` ran the full 172-window rolling
aggregate (this project's standing methodology) for baseline vs. the
`(8%, 60d)` candidate:

| Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Baseline (SMA 200, ATR x2.5, T+2) | 21.77% | 22.13% | 8.31% | -83.40% | 11.1 |
| Candidate (+ Trailing Stop 8%, cooldown 60d) | 26.75% | 27.70% | 13.37% | -61.65% | 17.8 |

This is a **net improvement across every metric** on the full 172-window
aggregate, not just the one event (Dot-com) the mechanism was designed to
target: Avg TWR up 4.98pp, Med TWR up 5.57pp, Worst TWR up 5.06pp, and
Worst DD shrinks by 21.75pp (-83.40% → -61.65%). Trade count rises from 11.1
to 17.8 average trades per window, as expected — the stop/cooldown/re-entry
cycle mechanically adds trades — but that added trading did not cost
return or increase worst-case drawdown; both moved in the favorable
direction.

Worth flagging as a correctness check on the validation script itself: the
baseline row's numbers (Avg TWR 21.77%, Worst DD -83.40%) exactly reproduce
`README.md` Table 3's already-published figures for the identical config
(SMA 200, ATR x2.5, T+2 on, S&P signal, 3x) — the rolling-window machinery
in `trailing_stop_validate.py` is computing the same baseline the rest of
this project already trusts, not a different or buggy number that happens
to look plausible.

## Segmentation Result

Windows were segmented by **start date**: the 1998-01-01 to 2001-12-31 band
(where this project's worst-known rolling windows all land — the dot-com
top hits a freshly-opened position with no accumulated cushion) vs. all
other starts.

| Strategy | Band | Avg TWR | N windows |
| :--- | :--- | ---: | ---: |
| Baseline | 1998-01-01 to 2001-12-31 starts | 16.42% | 31 |
| Baseline | Other starts | 22.94% | 141 |
| Candidate | 1998-01-01 to 2001-12-31 starts | 19.72% | 31 |
| Candidate | Other starts | 28.29% | 141 |

Stated plainly: the improvement is **not concentrated in the worst-window
band that originally motivated this investigation** — if anything it is
*larger* outside that band. The dot-com-adjacent band improves by +3.30pp
(16.42% → 19.72%); the other 141 windows improve by +5.35pp (22.94% →
28.29%). The band that this whole investigation was built around *does*
improve — the mechanism is not failing to help dot-com — it just doesn't
help it more than it helps everywhere else. That makes this look like a
**broadly beneficial open-position risk-management addition rather than a
narrow dot-com-specific patch**, which is a stronger, more general finding
than the original motivation set out to find. But it also means the
narrower question — "does this actually target dot-com specifically" — has
an honest, qualified answer: yes, the dot-com-era band's own numbers do
improve, just not by more than the rest of history does.

## Verdict / Recommendation

This project's established convention (`vix_threshold`, `atr_spike_multiplier`,
`sma_slope_lookback`) is to state findings by what the numbers show, not by
how promising the idea sounded going in. Of those three: `vix_threshold`
was a real, consistent effect but demonstrated to rest almost entirely on
one historical event (COVID) recurring — narrow, not recommended for
adoption without more validation. `sma_slope_lookback`'s underlying
hypothesis (dot-com as a re-entry/whipsaw problem) was disproven outright —
zero effect on every event, net negative on the full aggregate — and was
shelved.

The trailing-stop candidate here (`8%` stop, `60d` cooldown) is materially
stronger than either: it improves every rolling-window aggregate metric
(Avg/Med/Worst TWR, Worst DD), it does not merely trade off return for
drawdown or vice versa, it helps all 5 sweep-tested crisis events with no
evidence of a costly whipsaw, and — unlike `vix_threshold` — its benefit is
not concentrated in a single historical episode; segmentation shows it
generalizes across the full 172-window history, including but not limited
to the band it was originally designed for. It also survived a fragility
check that a naive automated pipeline would have missed: the mechanically
top-ranked combination `(5%, 60d)` was caught and rejected for an 8.6x
cooldown-neighbor cliff before this weaker-but-smoother candidate was ever
run through rolling validation.

That said, **this is not yet a recommendation to adopt it in `bot.py`.**
The 172 rolling windows used above all have start dates between 1986-04-29
and 2000-07-28 (26-year spans extending out to roughly today); this
finding used the whole selection-and-validation pipeline against that one
overlapping window set, with no train/test split. This project's own prior
work is a direct caution here: `docs/out-of-sample-validation-2026-07-28.md`
found that a mechanically-selected configuration which looked strong on the
same kind of full-history rolling aggregate ranked only #30 of 44 when
evaluated on a genuinely held-out period — a strong in-sample rolling
result was not, by itself, sufficient evidence of a generalizing edge. The
same caveat applies here: this candidate has not been tested
out-of-sample, and it should be before being recommended for `bot.py`.

**Recommendation:** this is a strong candidate for the next validation
step — out-of-sample testing following the train/test-split approach in
`docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md` —
not yet a final adoption recommendation. It stays an opt-in, off-by-default
experimental param (`trailing_stop_pct`/`trailing_stop_cooldown_days` on
`SMATrendFollowing`) pending that further validation, consistent with how
`vix_threshold`, `atr_spike_multiplier`, and `sma_slope_lookback` were all
handled.
