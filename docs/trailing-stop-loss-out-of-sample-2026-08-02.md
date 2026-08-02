# Trailing-Stop-Loss Out-of-Sample Validation (2026-08-02)

## Method

`backtest/trailing_stop_out_of_sample.py` reused the calendar-cutoff design
already established in `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`:
a **selection phase** restricted to the 45 rolling windows whose full 26-year
span ends by `2016-01-01` (no calendar overlap with the evaluation period),
picking the `(pct, cooldown)` combination with the largest rolling Avg TWR
improvement over baseline, then an **evaluation phase** running a single
non-rolling backtest of all 29 variants (baseline + 28 combinations) from
`2016-01-01` to today (`period_years=10`, floored per the constraint carried
over from the original out-of-sample check). Full rationale is in
`docs/superpowers/specs/2026-08-02-trailing-stop-out-of-sample-design.md`.
The evaluation-phase baseline row (`19.20%` TWR, `-72.26%` Max DD, `5`
trades) reproduces `docs/out-of-sample-validation-2026-07-28.md`'s
independently-published row for the identical config exactly — the sanity
check passed cleanly.

## Selection Result

The mechanical top pick from the 45 pre-2016 windows is **`(10%, 40d)`**,
+3.66pp Avg TWR improvement over baseline. Its neighbor columns show a
cliff: the cooldown axis collapses to `+0.46pp` at `20d` and flips negative
to `-0.32pp` at `60d` — an order-of-magnitude drop (and a sign flip on one
side) from a single grid step, the same non-monotonic-cliff pattern this
project has already flagged three times (Table 4's ATR sweep, Phase 6's
`atr_spike_multiplier`, and the original trailing-stop plan's own `(5%,
60d)` rejection). Its pct-axis neighbors are comparatively smooth
(`(8%,40d)=+2.57pp`, `(12%,40d)=+2.31pp`, 63-70% of the top value), but one
fragile axis is enough to fail the same-order-of-magnitude test applied
elsewhere in this project.

Every other candidate with a meaningfully positive improvement (>2pp) shows
the identical problem on at least one axis:

- `(12%, 20d)` +2.67pp — smooth on cooldown (`98%`, `86%` of its own value)
  but its pct-neighbors collapse to `17%` and `14%` of its own value.
- `(12%, 10d)` +2.62pp — smooth cooldown-side, but one pct-neighbor
  (`15%,10d`) drops to `14%`.
- `(8%, 40d)` +2.57pp — severe cliffs on both axes, including a sign flip
  to `-5.19pp` one pct step away.
- `(8%, 60d)` (the already-published pick) +2.48pp in this selection-phase
  metric — smooth on its only cooldown-neighbor, but both pct-neighbors are
  negative (`-4.98pp`, `-0.32pp`), a severe cliff.

The only region of the grid with genuinely smooth neighbors on both axes is
the `15%`/`20%` band, where the improvement itself is negligible
(`~0.38pp` and `~0.00pp` respectively) — not a usable positive pick. **No
candidate in this sweep combines a meaningful in-sample improvement with
smoothness on both grid axes.** Under the fragility heuristic used
throughout this project, the pre-2016 selection phase does not produce a
trustworthy single winner; `(10%, 40d)` is carried forward only as "the
mechanical pick," explicitly flagged as fragile, not as a validated choice.

## Evaluation Result

| Flagged row | Selection-phase improvement | OOS rank (of 29) | OOS TWR | OOS Max DD |
| :--- | ---: | :--- | ---: | ---: |
| `(10%, 40d)` — mechanical pick, flagged fragile | +3.66pp | **#3/29** | 28.89% | -52.17% |
| `(8%, 60d)` — published pick, flagged fragile | +2.48pp | **#20/29** | 22.50% | -48.73% |
| baseline (no stop) | — | #23/29 | 19.20% | -72.26% |

The two flagged rows generalized very differently despite both being
flagged fragile in-sample. `(10%, 40d)` ranked in the top decile
out-of-sample (#3 of 29) — the fragility flag did not predict poor
generalization here. `(8%, 60d)`, the pick already published in
`docs/trailing-stop-loss-finding-2026-08-01.md`, ranked only #20 of 29 —
bottom third of all trailing-stop variants tested, barely ahead of the
plain baseline (#23) and well behind combinations that were never selected
by any prior candidate procedure. This is closer to (though not as severe
as) the `docs/out-of-sample-validation-2026-07-28.md` precedent, where a
mechanically-selected configuration that looked strong in-sample ranked
#30 of 44 out-of-sample — a strong in-sample story that did not hold up.

Zoomed out, most of the grid still beats baseline out-of-sample: 22 of the
28 trailing-stop combinations rank above the `19.20%` baseline TWR, and
every one of those 22 also improves Max DD, several substantially (baseline
`-72.26%` vs. e.g. `-52.17%` at the mechanical pick). Only 6 combinations
underperform baseline, all from the weakest ends of the grid (`5%` stops,
or `7%`/`8%` paired with `10d` cooldown). The best out-of-sample performers,
`(12%, 20d)` and `(12%, 40d)` (both 29.07% TWR, -60.13% Max DD, rank #1/#2),
were never selected by the pre-2016 in-sample procedure — their own
selection-phase improvements (+2.67pp, +2.31pp) were smaller than several
rejected candidates, and their pct-axis neighbors were themselves cliffy.

## Verdict / Recommendation

The trailing-stop mechanism as a *category* holds up reasonably well
out-of-sample: a clear majority of tested combinations (22 of 28) beat the
no-stop baseline on both return and drawdown over the untouched 2016-today
period, consistent with `docs/trailing-stop-loss-finding-2026-08-01.md`'s
finding that the mechanism's drawdown benefit is its strongest and most
robust property.

But neither validated selection procedure in this project's history has
produced a trustworthy way to pick the *specific* `(pct, cooldown)` point:
the Selection Result above shows no candidate combining meaningful
in-sample improvement with cross-axis stability, and the one point already
published — `(8%, 60d)` — specifically underperforms its peers
out-of-sample (#20 of 29), even though it still beats the plain baseline.
The strongest out-of-sample performers (`12%` stop, `20d`/`40d` cooldown)
were not reachable by either this project's original event-relative
selection or this pre-2016 rolling-window selection.

**This is not a recommendation to adopt `(8%, 60d)`, or any single specific
point, in `bot.py`.** The category-level result is encouraging enough to
keep investigating, but the point-selection problem is unresolved across
two independent validation attempts now, and — per
`docs/trailing-stop-loss-finding-2026-08-01.md`'s standing caveat — none of
this has been re-run with commission or tax costs, which would erode
whatever edge survives. It stays an opt-in, off-by-default experimental
param on `SMATrendFollowing` pending further work. If a follow-up is
pursued, two things stand out from this data: the widest tested stops
(`10-12%`) generalized better than the narrower published one (`8%`), and a
selection criterion that rewards cross-axis smoothness directly — rather
than filtering the mechanical winner after the fact — might avoid landing
on a point like `(8%, 60d)` in the first place.
