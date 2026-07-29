# Out-of-Sample Validation of Table 4's "Best Practice" Pick (2026-07-28)

## Method

Table 4 (`README.md`) picks a "best real-world practice" SMA/EMA configuration
by grid-searching 44 parameter combinations against one rolling-window
backtest history — **172** overlapping windows, monthly-stepped, start dates
1986-04-29 to 2000-07-28, each window 26 years long (so individual windows'
spans extend as late as the run date that generated Table 4) — and
mechanically taking the highest average TWR after excluding the worst
drawdown quartile. This raises an obvious question: does that pick reflect a
real, generalizing edge, or did the search simply curve-fit to the one
history it was run against? `backtest/validate_out_of_sample.py` tests this
with a calendar-cutoff train/test split — full rationale, including why a
simpler "split by window start date" approach was rejected as leaky, is in
`docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`. In
short: **selection phase** re-runs the same 44-variant sweep restricted to
windows whose full 26-year span ends by **2016-01-01** (45 monthly-stepped
windows, start dates 1986-04-29 through **1989-12-28** — note 1990-01-01 is
the filter's cutoff *bound*, `2016-01-01 minus 26 years`, not a date any
monthly-stepped candidate actually lands on; 1989-12-28 is the last real
candidate at or before it — each window's span fully containing the dot-com
bust and the 2008 GFC), and picks a winner using the same
`pick_best_practice()` logic Table 4 uses (which, in this run, excluded 11 of
the 44 selection-phase variants via the worst-drawdown-quartile screen before
picking the highest Avg TWR among the rest). **Evaluation phase** then runs
all 44 variants once each — a single, non-rolling `Backtester` run, not a
rolling sweep — over the untouched **2016-01-01 to 2026-01-01** period (10
years — floored to a whole integer because `pd.DateOffset(years=...)`
rejects fractional values, which drops roughly the most recent 7 months of
2026 data from this evaluation), which includes the COVID crash and the 2022
bear.

**Important caveat on "untouched":** the 2016-01-01–2026-01-01 evaluation
period is untouched by *this script's own* 45-window selection phase — but
it is emphatically **not** untouched by Table 4's *original* 172-window
selection sweep. 127 of Table 4's 172 windows extend past 2016-01-01, and the
average Table 4 window overlaps the 2016-2026 evaluation span by roughly
**39%**. That means Table 4's published pick was chosen by a sweep in which
the 2016-2026 period was already a substantial contributor — so evaluating
that same pick against 2016-2026 below is an in-sample sub-period check, not
a genuine out-of-sample test. See Result and Interpretation for what this
does and doesn't tell us.

## Result

Run via `python backtest/validate_out_of_sample.py` on 2026-07-28; full
output in `backtest/out_of_sample_output.md` and reproduced in full in the
[Appendix](#appendix-full-evaluation-tables) below. Resolved run parameters
for this specific run: CUTOFF=2016-01-01, evaluation end_dt=2026-01-01
(period_years=10, floored), 45 selection-phase candidate windows
(1986-04-29 to 1989-12-28).

**In-sample winner** (selected from the 45 pre-2016 windows only): **SMA,
ATR x1.5, Signal = S&P 500 (^GSPC), T+2 = On** — Selection-phase Avg TWR
**22.71%**, Worst DD **-81.37%**.

This is *not* the same variant as Table 4's published "Best Practice" pick
(SMA, ATR x3.0, Signal = Own ^NDX, T+2 = Off, Avg TWR 24.53%, Worst DD
-83.08%) — restricting the training window set from the full 172-window
history down to the 45 pre-2016 windows changed which variant the mechanical
selection process picks. As a sanity check, this run's winning variant
(x1.5/S&P/On) is not a fluke or a bug: it was the *second*-place variant in
Table 4's own full-history sweep (24.41% Avg TWR, -81.38% Worst DD), so
22.71%/-81.37% from a smaller, older window set is in the same rough range,
not off by an order of magnitude.

**Out-of-sample** (2016-01-01 to 2026-01-01, single non-rolling run, and the
only genuinely leak-free out-of-sample result in this document — see the
caveat above): this in-sample winner scored TWR **27.91%**, Max DD
**-67.15%** — **rank #30 of 44**, the bottom third of all variants tested.
**This is a rank-based finding, not an absolute-return failure**: 27.91% is
*above* this variant's own 22.71% selection-phase average — the strategy
still made money and beat its own in-sample track record on genuinely
unseen data. "Rank #30 of 44" means 29 of the other 43 variants would have
scored even higher over this same 2016-2026 period — i.e. the selection
*process* failed to identify the best-ranking variant, not that the variant
it picked lost money or badly underperformed in absolute terms.

**Out-of-sample-best variant DIFFERS** from the in-sample winner: SMA, ATR
x1.5, Signal = S&P 500 (^GSPC), **T+2 = Off** — TWR **39.55%**, Max DD
**-58.97%** (rank #1 of 44). Notably, this is the *same* ATR/signal
combination as the in-sample winner, differing only in the T+2 setting
(Off vs. On) — flipping that one switch accounts for the full gap between
out-of-sample rank #1 and rank #30.

**Distribution context** (all 44 evaluated variants, 2016-2026 TWR): min
**15.70%**, median **30.00%**, max **39.55%** — a 23.85-percentage-point
spread from bottom to top. Rank #30's 27.91% sits just below the median (in
the lower-middle of the pack, not a dramatic outlier), and rank #11's 33.29%
sits comfortably in the upper half. Full per-variant figures are in the
[Appendix](#appendix-full-evaluation-tables).

**For reference — not an out-of-sample result.** Table 4's actual published
pick (SMA, ATR x3.0, Own ^NDX, T+2 Off) — which this validation's restricted
selection did *not* choose — placed **#11 of 44** when evaluated on
2016-2026 (TWR 33.29%, Max DD -69.96%), right at the top-quartile boundary
(44/4 = 11). This number is still worth recording, but it must be read
correctly: it is an **in-sample sub-period statistic, not an
out-of-sample/holdout result**. 2016-2026 sits substantially inside Table
4's own 172-window selection sample — 127 of 172 windows extend past
2016-01-01, and the average Table 4 window overlaps the 2016-2026 span by
roughly 39% — so this period already helped select that pick via Table 4's
own sweep, long before this "evaluation" ever ran. Put plainly: **Table 4's
published pick has not been tested out-of-sample by this work at all.** It
was never a candidate in the leak-free pre-2016-restricted selection above
(a different variant won there), and it cannot be fairly evaluated on
2016-2026 either, for the reason just given. The *only* genuinely leak-free,
out-of-sample finding in this document is the #30-of-44 result reported
above, for the variant the pre-2016-restricted selection actually picked
(SMA/x1.5/S&P 500/T+2-On) — that finding stands as reported.

Both evaluation tables have the expected row counts: 20 SMA rows, 24 EMA
rows, all 45/45 selection-phase candidate windows accepted for every
variant — no rejected windows, no missing data.

## Interpretation

Two distinct findings come out of this run:

1. **The selection process itself is unstable.** Restricting the training
   window set to pre-2016 history changed which of the 44 variants
   "wins" — the process did not reproduce Table 4's published pick. That
   instability is itself a symptom of the overfitting risk flagged during
   Table 4's original review (the non-monotonic ATR sweep around x3.0).
   A selection process that finds a real, robust edge should be reasonably
   stable to which slice of history it's trained on; this one was not.
2. **The variant this run's process actually picked performed poorly
   out-of-sample *in relative terms*** — rank 30 of 44 (bottom third), well
   below both its own selection-phase standing and the out-of-sample-best
   variant (11.6 percentage points of TWR away, from a one-parameter flip).
   This is a rank-based finding, not an absolute-return failure: the
   variant still returned 27.91% annualized out-of-sample, above its own
   22.71% selection-phase average — it made money and beat its own
   in-sample track record. What failed was the selection *process*'s
   ability to identify the best-ranking variant among 44, not the chosen
   variant's ability to generate returns. That is evidence this instance of
   "grid search 44 variants, take the max" found noise in the pre-2016
   window set rather than a generalizing edge for rank-optimality — not
   evidence the resulting strategy is unprofitable.

That said, this result does not indict Table 4's actual published pick
either — but not because it "survived" a holdout test. It never took one.
That specific variant (x3.0/Own/Off) — which this restricted-history
process never had the chance to select, since it wasn't the pre-2016
winner — placed #11 of 44 when scored on 2016-2026, but as established
above, that number is an in-sample sub-period statistic, not an
out-of-sample result: 2016-2026 was already substantial evidence feeding
Table 4's own 172-window selection sweep. So the honest read is: the
mechanical "maximize-Avg-TWR" selection procedure is demonstrably sensitive
to which window set feeds it (evidence of overfitting risk in the
*method*) — and, separately, **Table 4's specific published config has not
been tested out-of-sample by any part of this work.**

Testing it properly is harder than simply picking an earlier cutoff: it
requires an evaluation period that starts *after every one* of Table 4's
172 selection windows ends. The latest of those windows starts 2000-07-28
and spans 26 years — ending **2026-07-28**, which is today. There is no
historical calendar day that both (a) contains real market data and (b)
sits entirely outside Table 4's own 172-window selection sample. The only
way to genuinely test Table 4's published pick out-of-sample is forward, on
data that does not exist yet — which is exactly what a **walk-forward
analysis** (rolling train/test splits, re-selecting and re-testing
repeatedly as new data arrives) is for. This reinforces, rather than
contradicts, this document's existing "walk-forward is the natural next
step" framing below: it isn't just a nice-to-have refinement here, it is
the only design that could actually answer the question this document set
out to answer for Table 4's specific pick.

**This is one train/test split**, with a small selection sample (45
overlapping windows) and a single non-rolling evaluation run — not a
repeated-fold walk-forward analysis. It produced exactly one genuinely
leak-free out-of-sample data point: the #30-of-44 result for the
pre-2016-restricted selection's actual winner (x1.5/S&P/On). It shows that
selection process *can* overfit to a given window set; it says nothing
evaluable, in either direction, about Table 4's own published pick, and it
does not prove the x1.5/S&P/On result would hold up under a different
cutoff. **Walk-forward analysis** (Approach B from the original method
comparison, using multiple rolling train/test splits instead of one fixed
cutoff) is the natural next step if this single-split result leaves open
questions — which, as just discussed, it does, particularly for Table 4's
pick.

## Limitations

- **Small selection sample**: 45 overlapping pre-2016 windows, not
  independent samples (same monthly-step overlap issue as Table 1-4,
  tracked separately — see below).
- **Single evaluation period**: one non-rolling backtest over
  2016-01-01–2026-01-01, not a rolling sweep — no error bars, no sense of
  how sensitive the out-of-sample numbers are to the exact start date.
- **The 2016-2026 evaluation period is not disjoint from Table 4's own
  selection sample**: 127 of Table 4's 172 windows extend past 2016-01-01
  (average overlap ~39% of the evaluation span), so the #11-of-44 figure
  for Table 4's published pick is an in-sample sub-period statistic, not an
  out-of-sample result — see Result and Interpretation above. Only the
  #30-of-44 figure for this validation's own pre-2016-restricted winner is
  genuinely leak-free.
- **Doesn't address the separately-tracked window-overlap problem**
  (`docs/optimization-analysis-2026-07-27.md` §7) — the 45 selection
  windows and Table 4's original 172 both suffer from the same
  monthly-step, 26-year-window overlap, so neither the selection-phase nor
  Table 4's original Avg/Worst TWR figures are drawn from independent
  samples.
- **One fixed cutoff (2016-01-01)**: results are specific to this split;
  not repeated across multiple cutoffs, so it can't distinguish "this
  method is unstable in general" from "this particular cutoff happened to
  produce a different winner."

## Appendix: Full Evaluation Tables

Reproduced verbatim from `backtest/out_of_sample_output.md` (generated by
`python backtest/validate_out_of_sample.py`, run 2026-07-28), so the
evidence behind the Result section above is committed and auditable rather
than living only in a gitignored scratch file.

```
RESOLVED RUN PARAMETERS: run date=2026-07-28 | CUTOFF=2016-01-01 | evaluation end_dt=2026-01-01 (period_years=10, floored) | selection-phase candidate windows=45 (1986-04-29 to 1989-12-28)
IN-SAMPLE WINNER: SMA | ATR=x1.5 | Signal=S&P 500 (^GSPC) | T+2=On
  Selection-phase (windows ending by 2016-01-01): Avg TWR 22.71% | Worst DD -81.37% (11 of 44 variants excluded by the drawdown screen)
  Out-of-sample (2016-01-01 to 2026-01-01): TWR 27.91% | Max DD -67.15% -> rank #30 of 44
  Out-of-sample best variant DIFFERS: SMA | ATR=x1.5 | Signal=S&P 500 (^GSPC) | T+2=Off (TWR 39.55%, Max DD -58.97%)
```

### SMA — Out-of-Sample Evaluation

| ATR | Signal | T+2 | TWR | Max DD | Trades |
| :--- | :--- | :--- | ---: | ---: | ---: |
| x1.5 | S&P 500 (^GSPC) | Off | 39.55% | -58.97% | 7 |
| x2.5 | Own (^NDX) | On | 37.52% | -69.96% | 5 |
| x1.5 | Own (^NDX) | Off | 34.84% | -62.35% | 8 |
| x3.0 | Own (^NDX) | Off | 33.29% | -69.96% | 5 |
| x2.5 | Own (^NDX) | Off | 33.02% | -69.96% | 6 |
| x2.0 | Own (^NDX) | Off | 32.95% | -62.35% | 7 |
| x1.5 | Own (^NDX) | On | 30.33% | -68.92% | 8 |
| x2.5 | S&P 500 (^GSPC) | Off | 29.94% | -62.79% | 5 |
| x2.0 | S&P 500 (^GSPC) | Off | 29.92% | -72.10% | 7 |
| x3.5 | Own (^NDX) | Off | 29.59% | -69.96% | 5 |
| x2.0 | Own (^NDX) | On | 28.37% | -69.96% | 7 |
| x1.5 | S&P 500 (^GSPC) | On | 27.91% | -67.15% | 7 | **<- IN-SAMPLE WINNER**
| x3.0 | S&P 500 (^GSPC) | Off | 25.61% | -62.35% | 5 |
| x2.0 | S&P 500 (^GSPC) | On | 23.92% | -62.90% | 6 |
| x3.0 | Own (^NDX) | On | 23.80% | -69.96% | 5 |
| x3.5 | S&P 500 (^GSPC) | Off | 22.76% | -64.73% | 5 |
| x3.5 | Own (^NDX) | On | 21.69% | -69.96% | 5 |
| x2.5 | S&P 500 (^GSPC) | On | 19.20% | -72.26% | 5 |
| x3.0 | S&P 500 (^GSPC) | On | 18.68% | -68.92% | 5 |
| x3.5 | S&P 500 (^GSPC) | On | 16.09% | -69.96% | 5 |

### EMA — Out-of-Sample Evaluation

| ATR | Signal | T+2 | TWR | Max DD | Trades |
| :--- | :--- | :--- | ---: | ---: | ---: |
| x2.5 | Own (^NDX) | Off | 36.98% | -71.00% | 2 |
| x2.5 | Own (^NDX) | On | 36.77% | -71.00% | 2 |
| x2.0 | Own (^NDX) | Off | 34.62% | -70.70% | 2 |
| x2.0 | Own (^NDX) | On | 34.15% | -71.28% | 2 |
| x1.5 | Own (^NDX) | On | 33.90% | -69.96% | 3 |
| None | Own (^NDX) | Off | 33.46% | -69.96% | 6 |
| None | Own (^NDX) | On | 33.33% | -69.96% | 5 |
| x1.5 | Own (^NDX) | Off | 32.52% | -69.96% | 3 |
| x3.5 | Own (^NDX) | On | 31.70% | -76.43% | 2 |
| x3.0 | Own (^NDX) | Off | 31.70% | -74.06% | 2 |
| x3.0 | Own (^NDX) | On | 31.03% | -75.35% | 2 |
| x3.5 | Own (^NDX) | Off | 30.78% | -76.43% | 2 |
| x3.0 | S&P 500 (^GSPC) | Off | 30.39% | -76.43% | 2 |
| x3.0 | S&P 500 (^GSPC) | On | 30.14% | -76.43% | 2 |
| x3.5 | S&P 500 (^GSPC) | On | 30.06% | -76.57% | 2 |
| x2.5 | S&P 500 (^GSPC) | On | 29.38% | -77.76% | 2 |
| x3.5 | S&P 500 (^GSPC) | Off | 28.65% | -78.98% | 2 |
| x2.5 | S&P 500 (^GSPC) | Off | 28.04% | -79.95% | 2 |
| x2.0 | S&P 500 (^GSPC) | On | 23.51% | -77.93% | 4 |
| x2.0 | S&P 500 (^GSPC) | Off | 23.39% | -77.61% | 4 |
| None | S&P 500 (^GSPC) | Off | 22.54% | -68.92% | 7 |
| None | S&P 500 (^GSPC) | On | 21.95% | -68.92% | 7 |
| x1.5 | S&P 500 (^GSPC) | Off | 18.56% | -71.00% | 5 |
| x1.5 | S&P 500 (^GSPC) | On | 15.70% | -72.85% | 5 |

**Distribution across all 44 rows** (both tables combined): min 15.70%
(EMA, x1.5/S&P/On), max 39.55% (SMA, x1.5/S&P/Off), median 30.00%.
