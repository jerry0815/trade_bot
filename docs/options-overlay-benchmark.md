# Options Overlay Benchmark (2018-01-02 to 2026-08-14)

Initial capital: $10,000. TQQQ actual prices; ^VXN as IV proxy.

| Metric | Model 1 — Buy & Hold TQQQ | Model 2 — Trend (SMA+ATR, no options) | Model 3 — Static Covered Calls | Model 4 — Dynamic Two-Sided Engine |
| --- | --- | --- | --- | --- |
| Initial Capital ($) | $10,000 | $10,000 | $10,000 | $10,000 |
| Ending Portfolio Value ($) | $126,369 | $2,980,809 | $89,685 | $741,190 |
| CAGR (%) | 34.25% | 93.76% | 29.01% | 64.85% |
| Max Drawdown (MDD %) | -81.75% | -33.26% | -30.14% | -70.73% |
| Max Drawdown Duration (Days) | 1,117 | 439 | 479 | 322 |
| Sharpe Ratio (Rf=4.5%) | 0.71 | 1.59 | 0.77 | 1.13 |
| Sortino Ratio | 0.93 | 1.96 | 0.84 | 1.11 |
| Calmar Ratio (CAGR / MDD) | 0.42 | 2.82 | 0.96 | 0.92 |
| Total Option Premium Collected ($) | $0 | $0 | $105,600 | $609,129 |
| Total Option Debit Paid ($) | $0 | $0 | $0 | $526,958 |
| Total Option P&L ($) | $0 | $0 | $-188,980 | $-283,273 |
| Option Win Rate (%) | n/a | n/a | 64.51% | 44.65% |
| Total Option Trades | 0 | 0 | 355 | 383 |

## How to read this

Models 2–4 share the identical 3-state equity sleeve, so any difference between them is attributable to the options overlay alone. Model 2 (no options) is the control.

Realized option P&L is settled into the compounding book (a covered-call loss reduces the capital that keeps compounding, exactly as in a real account), so returns and drawdowns are internally self-consistent even when cumulative option P&L is large relative to the book.

### Modeling caveats — this is a strategy-comparison signal, not tradeable P&L

- Options are cash-settled at intrinsic on expiry (captures capped upside on covered calls and tail losses on short puts without modelling assignment).
- Vol input is `^VXN` as a TQQQ IV proxy; skew is a fixed multiplicative offset, not a fitted surface.
- TQQQ's actual (already-3x) daily returns drive the equity sleeve; the cash sleeve earns a flat `cash_yield`.
- Not modelled: bid/ask, fills, commissions, early assignment, borrow.

See `options/README.md` for model definitions and accounting assumptions.
