# QQQ (1x) Strategy Comparison (2026-08-06)

## Question

README Table 1's 1x tier already reports SMA-200-on-^NDX numbers scaled to
QQQ's 0.20% expense ratio, but it has never been run through the same
signal-source sweep (NDX-own vs. S&P-signal vs. dual-signal agreement) or
had the trailing stop applied at 1x — those were only tested at 3x (Table
4). Two things were open: does the signal-source ranking from Table 4 hold
at 1x, and does this table's Buy & Hold / NDX-own[T+2] rows actually agree
with Table 1's already-published 1x numbers (a sanity check on the new
sweep script itself)?

## Method

`backtest/qqq_strategy_sweep.py`, 172-window rolling aggregate,
`^NDX`/1x with QQQ's 0.20% expense ratio (same convention as Table 1's 1x
tier), SMA 200 (ATR x2.5), pre-tax. Sweeps the same signal sources as Table
4 (NDX-own, S&P-signal, dual-signal agreement, each with/without T+2) plus
the trailing stop (8%/60d, peak anchor) on the two most relevant setups, at
1x instead of 3x.

## Result

| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold | 11.65% | 12.06% | 6.12% | -82.99% | 1 |
| NDX own signal | 13.93% | 14.19% | 8.48% | -35.77% | 15 |
| NDX own signal [T+2] | 13.89% | 14.10% | 8.70% | -35.77% | 13 |
| S&P 500 signal | 13.61% | 13.93% | 8.64% | -35.77% | 12 |
| S&P 500 signal [T+2] | 13.21% | 13.74% | 7.68% | -35.77% | 11 |
| Dual-signal agreement | 14.69% | 14.91% | 8.89% | -35.77% | 9 |
| Dual-signal agreement [T+2] | 14.23% | 14.49% | 8.21% | -37.84% | 9 |
| S&P 500 signal [T+2] + Trailing Stop 8%/60d | 12.52% | 13.02% | 7.64% | -24.94% | 18 |
| Dual-signal agreement + Trailing Stop 8%/60d | 12.89% | 13.36% | 8.05% | -24.94% | 18 |

Cross-check against already-published numbers:

| Row | This table | Table 1 (1x tier) | Table 3 (1x tier) |
| :--- | ---: | ---: | ---: |
| Buy & Hold | 11.65% | 11.65% | 11.65% |
| NDX own signal [T+2] | 13.89% | 13.89% | — |
| S&P 500 signal [T+2] | 13.21% | — | 13.21% |

All three rows reproduce their Table 1 / Table 3 counterparts exactly.

## Findings

**1. The reproduction rows are a validation, not new information.** Table
1's 1x tier already runs on `^NDX` scaled to QQQ's expense ratio, so
`qqq_strategy_sweep.py`'s Buy & Hold, NDX-own[T+2], and S&P-signal[T+2] rows
are the same computation as Table 1/Table 3, run through a different script.
The exact match (to the basis point) is useful as a script cross-check but
should not be read as an independent confirmation from new data.

**2. The genuinely new result: dual-signal agreement is the best 1x setup,
same as it is at 3x.** Dual-signal agreement (no T+2), never tested at 1x
before, posts 14.69% Avg TWR — ahead of every single-signal variant and
Buy & Hold — with the fewest trades (9). This matches Table 4's 3x finding
(dual-signal agreement wins on every return metric with the fewest trades)
and extends it to the 1x tier for the first time.

**3. The trailing stop's trade-off looks the same at 1x as at 3x.** Worst DD
improves sharply (-35.77%/-37.84% -> -24.94%) for roughly double the trades
(9-13 -> 18) and a ~2pp Avg TWR cost — the same shape as Table 4's 3x
trailing-stop rows, just compressed by the lower leverage.

## Answer to the question asked

Yes on both counts: the reproduction rows confirm the new sweep script
agrees with the already-published Table 1/Table 3 numbers exactly, and the
signal-source ranking from Table 4 (dual-signal agreement wins) carries over
unchanged to the 1x tier. Nothing here overturns or qualifies the 3x
findings — it is confirmatory, plus two new rows (dual-signal, dual-signal +
stop) that Table 1 never tested.

## Caveats

- Uses `^NDX` index data scaled to QQQ's 0.20% expense ratio, not QQQ's own
  post-1999 price history — QQQ itself only launched in March 1999, so the
  full 1986-2000 rolling-window range used throughout this README is only
  reachable via the index proxy. This is the same convention Table 1's 1x
  tier already uses, not a new limitation introduced here.
- Single run, same signal-source sweep as Table 4 — subject to the same
  non-OOS-validated caveat noted there.
- Overlapping-window caveat applies: 172 monthly-stepped windows share
  nearly all their history with their neighbors.
- Pre-tax, no commissions/slippage.

## Follow-ups

- Re-run against QQQ's actual post-1999 price history for the post-1999
  subset of windows, to check whether the expense-ratio-adjusted `^NDX`
  proxy and QQQ's own tracking behavior diverge in any window.
- Tax-aware re-run at 1x, matching `docs/taxable-account-2026-08-06.md`'s
  3x tax treatment.
