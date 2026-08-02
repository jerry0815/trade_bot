# Trailing-Stop-Loss Tax-Aware Out-of-Sample Re-Run (2026-08-02)

## Method

Follow-up to `docs/trailing-stop-loss-out-of-sample-2026-08-02.md`, which
flagged its evaluation as "not cost-adjusted" — an open caveat repeated in
every trailing-stop finding to date. `backtest/trailing_stop_tax_aware_out_of_sample.py`
re-runs the exact same 29-variant, `2016-01-01`-to-today evaluation with
`Backtester(apply_tax=True)`, an existing engine feature (25% short-term /
15% long-term capital-gains rate, applied on every position exit) — no
engine change, no new modeling. Commission/slippage remain unmodeled and
out of scope, per the original design spec's explicit deferral of that as
"a distinct follow-up."

## Result

Every variant loses 2.5-7.7pp of TWR to tax, and the size of the loss
scales with trade count: baseline (5 trades) loses only +2.47pp, while
`(5%, 10d)` (25 trades) loses +7.69pp. This is expected — trailing-stop
exits are almost always held under a year, so their gains are taxed at the
25% short-term rate baseline mostly avoids by holding for years.

The relative ranking is mostly preserved, but not entirely:

| Row | Pre-Tax TWR | After-Tax TWR | Edge over baseline (pre-tax → after-tax) | Rank (of 29) |
| :--- | ---: | ---: | :--- | :--- |
| `(12%, 20d)` / `(12%, 40d)` — best OOS performers | 29.07% | 25.69% | +9.87pp → +8.96pp (91% retained) | #1/#2 both phases |
| `(10%, 40d)` — pre-2016 selection winner, flagged fragile | 28.89% | 25.17% | +9.69pp → +8.44pp (87% retained) | #3 both phases |
| `(8%, 60d)` — published pick, flagged fragile | 22.50% | 18.98% | +3.30pp → +2.25pp (68% retained) | #20 both phases |
| baseline (no stop) | 19.20% | 16.73% | — | #23 pre-tax → #21 after-tax |

The top performers keep most of their edge (87-91% retained) because they
trade infrequently (5-7 trades, same order as baseline). The published pick
keeps less (68%) because it trades more (9) for a thinner edge to begin
with. Two variants flip from beating baseline to losing to it once tax is
applied: `(10%, 10d)` (20.20% → 16.44%, baseline 16.73%) and `(5%, 10d)`
(21.62% → 13.93%) — both `10d`-cooldown, high-turnover configs (10 and 25
trades respectively, the two highest trade counts in the whole grid).
Category-wide, 20 of 28 trailing-stop variants still beat baseline after
tax, down from 22 of 28 pre-tax — a small, concentrated erosion, not a
broad reversal.

## Verdict

**The tax caveat is substantially addressed, and the news is good: a real
edge survives.** The best-performing configurations (`10-12%` stops,
`20-40d` cooldowns) retain 87-91% of their out-of-sample edge over baseline
after realistic capital-gains tax — this was the main open question left by
`docs/trailing-stop-loss-out-of-sample-2026-08-02.md`, and it resolves in
the mechanism's favor.

This does not resolve the other open problem from that same document: no
selection procedure tested so far reliably picks the best specific point,
and the already-published `(8%, 60d)` candidate is still a mediocre
performer (#20 of 29, both before and after tax) despite still beating
baseline. It also does not model commissions or slippage, which remains a
distinct, unaddressed follow-up.

**Net effect on the earlier recommendation:** still not a recommendation to
adopt `(8%, 60d)` specifically. But the category-level case for the
mechanism is now stronger than before — the previously-hypothetical "the
edge might not survive costs" risk is now a tested, mostly-negative result
for the top performers. The clearest new, concrete guidance: **avoid
`10d`-cooldown configurations** — they were already unremarkable pre-tax
and are the only band that loses its edge over baseline entirely once tax
is applied, consistent with their outsized trade counts.
