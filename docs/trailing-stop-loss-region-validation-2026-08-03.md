# Trailing-Stop Region Rolling-Window Validation (2026-08-03)

## Method

`backtest/trailing_stop_region_validate.py` runs this project's standing
172-window rolling methodology (pre-tax, `^NDX`/3x, S&P signal, SMA 200 /
ATR x2.5 / T+2) for baseline plus five trailing-stop configurations. It
exists to close a gap: `backtest/trailing_stop_validate.py` only ever ran
the rolling aggregate for `(8%, 60d)`, and
`docs/trailing-stop-loss-out-of-sample-2026-08-02.md` subsequently showed
that configurations which score better out-of-sample —
`(10%, 40d)`, `(12%, 20d)` — had never been through the aggregate at all.

All four corners of the `10-12%` × `20-40d` neighborhood are included, to
test whether that whole region holds up rather than isolated points (the
point-selection problem two independent selection procedures have now
failed to solve).

**Reproduction check passed exactly.** `(8%, 60d)` returns Avg TWR 23.43%,
Med 23.92%, Worst TWR 12.30%, Worst DD -64.78%, Avg Trades 17.8, and
baseline returns 21.77% / 22.13% / 8.31% / -83.40% / 11.1 — digit-for-digit
identical to `docs/trailing-stop-loss-finding-2026-08-01.md`'s published
table. This script computes the same thing the earlier one did.

## Result

| Config | Avg TWR | vs. baseline | Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: |
| baseline | 21.77% | — | -83.40% | 11.1 |
| 8%, 60d | 23.43% | +1.66pp | **-64.78%** | 17.8 |
| 10%, 20d | 21.85% | +0.08pp | -87.20% | 15.6 |
| 10%, 40d | 25.54% | **+3.77pp** | -86.20% | 13.6 |
| 12%, 20d | 24.80% | +3.03pp | -83.40% | 12.1 |
| 12%, 40d | 24.48% | +2.71pp | -83.40% | 11.1 |

Two findings, the second of which is decisive.

**1. The "robust region" hypothesis fails.** `(10%, 20d)` improves Avg TWR
by +0.08pp — indistinguishable from zero — sitting directly between
`(10%, 40d)` at +3.77pp and `(12%, 20d)` at +3.03pp. The neighborhood is
not uniformly good; it has a hole in the middle. Averaging over the region
would not have rescued the point-selection problem.

**2. Drawdown protection and return improvement are mutually exclusive
across this grid.** The aggregate `Worst DD` column understates this, since
it is a single worst-case scalar. Per-window comparison across all 172
windows:

| Config | Windows drawdown improved | Worsened | Identical | Mean Max DD |
| :--- | ---: | ---: | ---: | ---: |
| baseline | — | — | — | -83.13% |
| 8%, 60d | **172** | **0** | 0 | **-64.77%** |
| 10%, 20d | 4 | 168 | 0 | -86.63% |
| 10%, 40d | 4 | 168 | 0 | -85.66% |
| 12%, 20d | 60 | 60 | 52 | -82.91% |
| 12%, 40d | 63 | 54 | 55 | -82.91% |

`(8%, 60d)` reduces drawdown in **every single one of the 172 windows**,
with no exceptions — mean Max DD -83.13% → -64.77%. That is the most
consistent result produced anywhere in this investigation.

The wider stops do the opposite of what the mechanism was built for. At
`10%`, drawdown is **worse** in 168 of 172 windows — the stop exits and
re-enters in a way that actively deepens worst-case losses while raising
average return. At `12%`, drawdown is a coin flip (60/60/52, mean unchanged
to within 0.2pp); the return gain comes with no crash protection at all.

## Correction to the prior recommendation

`docs/trailing-stop-loss-out-of-sample-2026-08-02.md` and the session
discussion following it treated `(10%, 40d)` as the strongest all-around
candidate, on the strength of its out-of-sample rank (#3 of 29) versus
`(8%, 60d)`'s (#20 of 29). **That was an error of exactly the kind this
investigation was set up to avoid**: a single 10-year window containing
5-7 trades was allowed to override a 172-window aggregate. On the
aggregate, `(10%, 40d)` makes drawdown worse 98% of the time.

The out-of-sample window is not wrong, it is just narrow — and on that one
window every config including `(8%, 60d)` improved drawdown
(-72.26% → -48.73%), so it did not discriminate on the dimension that
turns out to matter. The out-of-sample table ranked variants by *return*;
the rolling aggregate shows that return ranking and drawdown behavior point
in opposite directions.

## Verdict

The trailing-stop mechanism is now well-characterized, and the honest
summary is that it is **a drawdown-reduction tool, not a return-enhancement
tool** — and only at the tighter stop widths.

`(8%, 60d)` has the strongest evidence of anything tested in this
investigation:

- Drawdown improved in **172 of 172** rolling windows, mean -83.13% → -64.77%.
- Drawdown also improved on the genuinely held-out 2016-today window
  (-72.26% → -48.73%), so the effect reproduces out-of-sample.
- Return improvement is positive but modest and consistent (+1.66pp Avg TWR
  rolling; 22.50% vs. 19.20% baseline out-of-sample).
- All 5 sweep-tested crisis events improved, none worsened
  (`docs/trailing-stop-loss-finding-2026-08-01.md`).

Its known costs are unchanged and still real: **60% more trading** (11.1 →
17.8 average trades per window), with commissions and slippage still
unmodeled, and a measured tax drag of 3.52pp on the out-of-sample window
(`docs/trailing-stop-loss-tax-aware-out-of-sample-2026-08-02.md`) — which
consumes most of the gross return improvement, though not the drawdown
benefit.

**Recommendation:** the `10%` and `12%` configurations should be dropped
from consideration entirely — they do not deliver crash protection, which
was the mechanism's entire motivation, and at `10%` they measurably worsen
it. If the trailing stop is adopted for anything, it should be `(8%, 60d)`,
adopted **for drawdown reduction**, with the explicit understanding that
its return contribution is roughly a wash after realistic costs. Whether
an ~18pp reduction in worst-case drawdown is worth ~60% more trading and a
near-zero net return effect is a risk-tolerance judgment, not something
these backtests can settle.
