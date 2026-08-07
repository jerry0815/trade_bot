# Taxable Account: Pre-Tax vs. After-Tax (2026-08-06)

## Question

Every backtest number published in this README up to Table 4/5 is pre-tax.
The peak-based trailing stop's return effect there is already close to flat
(Table 4: 23.43% vs. 21.77% for S&P+T+2, and 24.59% vs. 25.81% for
dual-signal), while its drawdown benefit is large. Does that balance survive
contact with realistic capital-gains tax in a taxable account — where the
stop's extra trades (18 vs. 9-11) mean more short-term-taxed exits?

## Method

`backtest/taxable_account_comparison.py`, 172-window rolling aggregate,
`^NDX`/3x, S&P-signal and dual-signal entries with and without the
peak-based trailing stop (8%/60d). Tax applied via the engine's existing
`Backtester(apply_tax=True)` feature — 25% short-term / 15% long-term
capital-gains rate on every position exit (engine defaults, the same rates
used in `docs/trailing-stop-loss-tax-aware-out-of-sample-2026-08-02.md`) —
no engine change, no new modeling. Commissions/slippage remain unmodeled,
consistent with the rest of this README.

## Result

| Setup | Pre-Tax Avg TWR | After-Tax Avg TWR | Tax Drag (pp) | After-Tax Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| S&P-signal [T+2] | 21.77% | 18.92% | +2.84 | -83.86% | 11 |
| S&P-signal [T+2] + peak stop 8/60 | 23.43% | 18.91% | +4.51 | -66.45% | 18 |
| Dual-signal | 25.81% | 23.61% | +2.19 | -87.57% | 9 |
| Dual-signal + peak stop 8/60 | 24.59% | 19.82% | +4.78 | -67.36% | 18 |

The pre-tax column reproduces Table 4's numbers for these four setups
exactly (21.77% / 23.43% / 25.81% / 24.59%).

## Findings

**1. The peak stop's pre-tax return advantage over no-stop disappears after
tax, and inverts for the dual-signal pair.** Pre-tax, S&P+stop already beats
S&P-no-stop (23.43% vs. 21.77%) and dual+stop is a near-wash against
dual-no-stop (24.59% vs. 25.81%). After tax: S&P+stop (18.91%) and
S&P-no-stop (18.92%) are now a dead heat — a difference of 0.01pp, well
inside noise — and dual+stop (19.82%) falls **below** dual-no-stop (23.61%)
by 3.79pp. The stop's return case, already unremarkable pre-tax, becomes
actively negative for the dual-signal pair once tax is realistic.

**2. Tax drag is roughly double for the stopped setups, and the mechanism is
turnover.** No-stop setups lose +2.84pp (S&P) / +2.19pp (dual) to tax;
stopped setups lose +4.51pp / +4.78pp — nearly double. The stopped setups
trade 18 times versus 9-11 for no-stop; each extra stop/re-entry cycle is a
position that's usually closed within a year, taxed at the 25% short-term
rate rather than compounding untaxed or eventually qualifying for the 15%
long-term rate. This is the same turnover-drives-tax-drag mechanism
`docs/trailing-stop-loss-tax-aware-out-of-sample-2026-08-02.md` found for
the peak stop's own parameter grid (drag scales with trade count there too).

**3. The drawdown benefit is untouched by tax.** After-Tax Worst DD still
improves sharply with the stop: -83.86% -> -66.45% (S&P pair), -87.57% ->
-67.36% (dual pair) — tax reduces *returns*, it doesn't touch the
crash-protection mechanism, which fires on price action independent of the
account's tax treatment.

## Answer to the question asked

**No, the balance does not survive.** Pre-tax, the peak stop looked like a
low-cost or even free way to cut drawdown. After realistic tax, that framing
breaks down for the dual-signal pair specifically (the stop becomes a net
return cost, not a wash) and the S&P pair's already-marginal edge is erased
entirely. The stop's value proposition in a taxable account is **drawdown
reduction only** — it should not be adopted there on the expectation of a
return benefit, even the small one the pre-tax numbers suggested.

## Caveats

- Fixed 25% short-term / 15% long-term capital-gains rates (engine
  defaults) — actual tax outcomes vary by bracket, jurisdiction, state
  taxes, and holding-period edge cases not modeled here.
- Only the peak-based stop (8%/60d) was tested here; the velocity stop
  (`docs/velocity-stop-2026-08-06.md`), which trades even more often
  (21-30 trades vs. 18), was flagged there as a follow-up for the same
  tax-aware treatment and would likely show a larger drag.
- Overlapping-window caveat applies: 172 monthly-stepped windows share
  nearly all their history with their neighbors.
- No commissions/slippage modeled, consistent with the rest of this README.

## Follow-ups

- Tax-aware re-run of the velocity stop (Table 6 /
  `docs/velocity-stop-2026-08-06.md`), whose higher trade count suggests a
  larger tax drag than the peak stop's.
- Sensitivity check across a range of short/long-term rate assumptions
  (e.g. 0%, 20%, 37% short-term) to see how far the stop's after-tax
  return case would have to move before it's competitive again.
- A tax-lot-aware account model (partial-year holds, wash-sale rules) if
  this ever moves from an illustrative backtest to a real trading decision.
