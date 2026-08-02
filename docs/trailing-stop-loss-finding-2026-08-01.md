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

**A one-day lookahead bug was found in `_apply_trailing_stop` during final
review and fixed; every number in this document is from the corrected code.**
The original implementation decided whether day `i` was a stop-exit day using
day `i`'s own Close, but `Backtester._run_portfolio_math` sells an exit day at
*today's open* — so the stop was reacting to a price that is not knowable until
after the trade it triggers has already executed. Every other signal in
`strat_backtest.py` avoids this via the `raw_signal.shift(1)` in
`_add_indicator_logic`; the trailing-stop overlay was the sole exception. The
fix lags the entire peak/breach calculation by one day (peak initialization,
peak update, and breach comparison all read `close[i-1]`, never mixing lagged
and unlagged reads). The correction materially reduced the measured benefit —
the pre-fix numbers overstated it roughly threefold on the rolling aggregate —
which is exactly why it is recorded here rather than silently patched. The
sweep, the candidate selection, and the rolling validation below were all
re-run from scratch on the corrected code; none of the pre-fix numbers were
carried over or relabeled.

## Sweep Result

`backtest/trailing_stop_sweep.py` swept `trailing_stop_pct ∈ {5%, 7%, 8%,
10%, 12%, 15%, 20%}` × `trailing_stop_cooldown_days ∈ {10, 20, 40, 60}` (28
combinations) against the live `bot.py` config (^NDX/3x, S&P-signal-driven,
SMA 200, ATR x2.5, T+2), reporting event-relative decline across 5 known
crises per combination (`backtest/trailing_stop_sweep_output.md`).

Applying the mechanical candidate-selection procedure (Task 3 Step 2 of
`docs/superpowers/plans/2026-08-01-trailing-stop-loss.md`) to the corrected
Dot-com rows, exactly four combinations clear the `>= 2.0pp` candidate bar,
and all four formally clear the non-fragility bar (`>= 1.0pp` on at least one
pct-neighbor and one cooldown-neighbor):

| Candidate | Dot-com Improvement (pp) | Cooldown-neighbor | Pct-neighbor(s) | Neighborhood shape |
| :--- | ---: | :--- | :--- | :--- |
| 5%, 60d | **+53.62** | (5%, 40d) = +1.77 | (7%, 60d) = +41.70 | **30x cliff** on cooldown axis |
| 7%, 60d | +41.70 | (7%, 40d) = +1.57 | (5%/8%, 60d) = +53.62 / +32.14 | **26x cliff** on cooldown axis |
| 8%, 60d | +32.14 | (8%, 40d) = +21.65 (1.48x) | (7%, 60d) = +41.70 (0.77x) | smooth on **both** axes |
| 8%, 40d | +21.65 | (8%, 60d) = +32.14 (1.48x) | (7%, 40d) = +1.57 | **14x cliff** on pct axis |

The mechanically top-ranked combination is `(5%, 60d)` at **+53.62pp**, the
single highest value anywhere in the 28×5 sweep. **It was rejected by hand**,
for the same reason the pre-fix analysis rejected the same combination: its
*cooldown*-neighbor `(5%, 40d)` scores only **+1.77pp**, a **30x** collapse
between adjacent cooldown values at the same stop width. That is the
non-monotonic-cliff overfitting signature this project has already rejected
twice — Table 4's original ATR sweep, and Phase 6's `atr_spike_multiplier` (a
huge win at 1.5x that vanished at 1.75x, see
`docs/session-handover-2026-08-01.md`). Notably the cliff got *sharper* after
the lookahead fix (8.6x pre-fix → 30x post-fix), not softer, so removing the
lookahead did not rehabilitate this combination. `(7%, 60d)` was rejected on
identical grounds (26x).

**The candidate carried forward is `(pct=8%, cooldown=60d)`**, Dot-com
`Improvement (pp)` **+32.14** — lower than the two rejected headline numbers,
but the only survivor whose neighborhood is smooth along *both* grid axes:
`(8%, 40d)` = +21.65pp (1.48x) and `(7%, 60d)` = +41.70pp (0.77x) are both the
same order of magnitude as it. The `60d` cooldown row as a whole declines
smoothly across stop width (+53.62 → +41.70 → +32.14 at 5/7/8%), which is a
coherent gradient rather than an isolated spike; the cliffs all live on the
cooldown axis at the tighter stops.

This is the same `(8%, 60d)` pair the pre-fix analysis landed on, but it was
re-derived from scratch against the corrected sweep rather than carried over —
the underlying improvement values, the ranking margins, and the cliff ratios
all changed.

**Effect on the other 4 events, at `(8%, 60d)`:** every event improved, none
worsened — no evidence of a costly whipsaw anywhere in the 5-event sweep for
this specific combination:

| Event | Baseline Decline | Stop Decline | Improvement (pp) |
| :--- | ---: | ---: | ---: |
| Black Monday 1987 | -65.91% | -19.55% | +46.36 |
| Dot-com crash | -83.25% | -51.11% | +32.14 |
| 2008 GFC | -31.77% | -17.95% | +13.82 |
| COVID crash | -69.61% | -42.69% | +26.92 |
| 2022 rate-shock bear | -51.69% | -38.06% | +13.63 |

## Rolling-Window Result

`backtest/trailing_stop_validate.py` ran the full 172-window rolling
aggregate (this project's standing methodology) for baseline vs. the
`(8%, 60d)` candidate:

| Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Baseline (SMA 200, ATR x2.5, T+2) | 21.77% | 22.13% | 8.31% | -83.40% | 11.1 |
| Candidate (+ Trailing Stop 8%, cooldown 60d) | 23.43% | 23.92% | 12.30% | -64.78% | 17.8 |

Every metric still moves in the favorable direction: Avg TWR up 1.66pp, Med
TWR up 1.79pp, Worst TWR up 3.99pp, and Worst DD shrinks by 18.62pp
(-83.40% → -64.78%). The drawdown effect is the largest and most robust part
of the result; the return effect is real but modest.

**Cost caveat.** Trade count rises from 11.1 to 17.8 average trades per window
— about 60% more trading — which is mechanically expected from the
stop/cooldown/re-entry cycle. This backtest is **commission-free and pre-tax**
(`apply_tax=False`, the default), so the +1.66pp Avg TWR improvement is a
gross figure that does not pay for that extra turnover. At a ~1.66pp edge, that
caveat is not cosmetic: realistic round-trip costs and short-term capital-gains
treatment on the added exits could consume a meaningful fraction of it, and
possibly all of it. The claim supported here is that the added trading did not
cost *gross* return and did not worsen drawdown — not that it is net-positive
after costs. Establishing the latter requires re-running with `apply_tax=True`
and a commission model, which has not been done. (Note that the pre-fix,
lookahead-inflated version of this document reported a +4.98pp Avg TWR gain,
where this caveat would have been far less consequential; it matters much more
at the corrected magnitude.)

Worth flagging as a correctness check on the validation script itself: the
baseline row's numbers (Avg TWR 21.77%, Worst DD -83.40%) exactly reproduce
`README.md` Table 3's already-published figures for the identical config
(SMA 200, ATR x2.5, T+2 on, S&P signal, 3x) — the rolling-window machinery
in `trailing_stop_validate.py` is computing the same baseline the rest of
this project already trusts. This also confirms the lookahead fix left the
`trailing_stop_pct=None` path untouched: the baseline row is unchanged to the
last reported digit from the pre-fix run.

## Segmentation Result

Windows were segmented by **start date**: the 1998-01-01 to 2001-12-31 band
(where this project's worst-known rolling windows all land — the dot-com
top hits a freshly-opened position with no accumulated cushion) vs. all
other starts.

| Strategy | Band | Avg TWR | N windows |
| :--- | :--- | ---: | ---: |
| Baseline | 1998-01-01 to 2001-12-31 starts | 16.42% | 31 |
| Baseline | Other starts | 22.94% | 141 |
| Candidate | 1998-01-01 to 2001-12-31 starts | 17.93% | 31 |
| Candidate | Other starts | 24.64% | 141 |

Re-derived from the corrected numbers, the segmentation conclusion is now
**weaker than the pre-fix version claimed**. The dot-com-adjacent band
improves by **+1.51pp** (16.42% → 17.93%); the other 141 windows improve by
**+1.70pp** (22.94% → 24.64%). The difference between those two segment
effects is **0.19pp** — small enough that this data does not support claiming
a direction at all.

This is a genuine change in the finding, not a restatement. The pre-fix
numbers showed +3.30pp in-band vs. +5.35pp out-of-band, a 2.05pp gap that the
earlier write-up described as the improvement being "if anything *larger*
outside" the worst-window band. Removing the lookahead shrank both effects and
collapsed the gap between them by an order of magnitude. The honest reading now
is that the improvement is **approximately uniform across both segments**: the
mechanism is neither a dot-com-specific patch nor demonstrably better outside
the dot-com band. It is a broad, small, evenly-distributed return improvement
paired with a substantial drawdown improvement.

The narrower motivating question — "does this actually target dot-com
specifically" — still has the same qualified answer, now with a smaller
margin: the dot-com-era band's own numbers do improve, but not by more than
the rest of history does.

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

The corrected trailing-stop candidate (`8%` stop, `60d` cooldown) still
compares favorably to both, but by a narrower margin than the pre-fix write-up
claimed. What holds up:

- It improves every rolling-window aggregate metric (Avg/Med/Worst TWR, Worst
  DD) rather than trading return against drawdown.
- The **drawdown** improvement is substantial and is the strongest part of the
  result: Worst DD -83.40% → -64.78%.
- It helps all 5 sweep-tested crisis events with no event worsening.
- Unlike `vix_threshold`, its benefit is not concentrated in a single episode
  or a single start-date band.
- It survived a fragility check a naive pipeline would have missed: the
  mechanically top-ranked `(5%, 60d)` was rejected for a 30x cooldown-neighbor
  cliff before this smoother candidate was validated.

What is weaker than previously stated:

- The gross return improvement is **+1.66pp Avg TWR, not +4.98pp** — the
  earlier figure was inflated by the one-day lookahead.
- That gross improvement is **not cost-adjusted**, against 60% more trading.
- The segmentation story is now **flat** (+1.51pp vs +1.70pp), not "larger
  outside the band."

**This is not a recommendation to adopt it in `bot.py`.** The 172 rolling
windows all have start dates between 1986-04-29 and 2000-07-28 (26-year spans
extending out to roughly today); this finding ran the whole
selection-and-validation pipeline against that one overlapping window set,
with no train/test split. This project's own prior work is a direct caution:
`docs/out-of-sample-validation-2026-07-28.md` found that a mechanically-selected
configuration which looked strong on the same kind of full-history rolling
aggregate ranked only #30 of 44 on a genuinely held-out period. That caveat
binds harder here than it did at the pre-fix numbers, because a +1.66pp
in-sample gross edge has much less room to survive both an out-of-sample haircut
and trading costs than a +4.98pp one did.

**Recommendation:** this remains a candidate for the next validation step —
out-of-sample testing following the train/test-split approach in
`docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`, ideally
alongside a cost/tax-aware re-run — not an adoption recommendation. It stays an
opt-in, off-by-default experimental param
(`trailing_stop_pct`/`trailing_stop_cooldown_days` on `SMATrendFollowing`)
pending that further validation, consistent with how `vix_threshold`,
`atr_spike_multiplier`, and `sma_slope_lookback` were all handled. If only one
follow-up is run, the drawdown result is the part most worth trying to confirm;
the return result is the part most likely to evaporate.
