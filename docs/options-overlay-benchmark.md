# Options Overlay Benchmark (2018-01-02 to 2026-08-14)

Initial capital: $10,000. TQQQ actual prices; ^VXN as IV proxy.

| Metric | Model 1 — Buy & Hold TQQQ | Model 2 — Trend (SMA+ATR, no options) | Model 3 — Static Covered Calls | Model 4 — Dynamic Two-Sided Engine |
| --- | --- | --- | --- | --- |
| Initial Capital ($) | $10,000 | $10,000 | $10,000 | $10,000 |
| Ending Portfolio Value ($) | $126,369 | $2,980,809 | $2,866,992 | $3,504,880 |
| CAGR (%) | 34.25% | 93.76% | 92.89% | 97.44% |
| Max Drawdown (MDD %) | -81.75% | -33.26% | -27.43% | -43.60% |
| Max Drawdown Duration (Days) | 1,117 | 439 | 320 | 230 |
| Sharpe Ratio (Rf=4.5%) | 0.71 | 1.59 | 1.75 | 1.54 |
| Sortino Ratio | 0.93 | 1.96 | 2.07 | 1.86 |
| Calmar Ratio (CAGR / MDD) | 0.42 | 2.82 | 3.39 | 2.23 |
| Total Option Premium Collected ($) | $0 | $0 | $2,724,875 | $1,911,400 |
| Total Option Debit Paid ($) | $0 | $0 | $0 | $604,861 |
| Total Option P&L ($) | $0 | $0 | $-144,242 | $240,933 |
| Option Win Rate (%) | n/a | n/a | 63.03% | 43.16% |
| Total Option Trades | 0 | 0 | 284 | 190 |

## How to read this

Models 2–4 share the identical 3-state equity sleeve, so any difference between them is attributable to the options overlay alone. Model 2 (no options) is the control.

Realized option P&L is settled into the compounding book (a covered-call loss reduces the capital that keeps compounding, exactly as in a real account), so returns and drawdowns are internally self-consistent even when cumulative option P&L is large relative to the book.

### Modeling caveats — this is a strategy-comparison signal, not tradeable P&L

- **Pricing vol** = `^VXN × 2.5`. `^VXN` is the *1×* Nasdaq-100 vol index, but these options are on *3×* TQQQ, whose realized vol ran ~2.5× VXN over 2018–2026 (median 2.51×). Pricing off raw VXN underprices every option ~2.5× and flips the ranking — it makes *buying* options look like free money and *selling* them look terrible. Results are highly sensitive to this multiplier (`OverlayConfig.pricing_iv_mult`); it sets implied ≈ realized (no vol-risk premium gifted to either side).
- Options are cash-settled at intrinsic on expiry (captures capped upside on covered calls and tail losses on short puts without modelling assignment).
- Skew is a fixed multiplicative offset, not a fitted surface.
- TQQQ's actual (already-3x) daily returns drive the equity sleeve; the cash sleeve earns a flat `cash_yield`.
- Not modelled: bid/ask, fills, commissions, early assignment, borrow.

See `options/README.md` for model definitions and accounting assumptions.
