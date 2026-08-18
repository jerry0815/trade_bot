# Extended backtest — reconstructed TQQQ, 1990–2026

Real TQQQ began 2010-02-11, so the primary benchmark
(`docs/options-overlay-benchmark.md`, 2018–2026) never saw a prolonged bear. This
run rebuilds a **synthetic TQQQ** from `^NDX` (history to 1985) and stress-tests the
strategies through **four** major bears — the 1990 Gulf-War recession, the
**dot-com collapse**, **2008**, and 2022 — the regimes that matter most for a 3×
leveraged product. See `options/reconstruct_tqqq.py`.

## Reconstruction & validation

Synthetic daily return = `3 × r_NDX − (0.95% expense + 2 × short_rate) / 252 + α`,
where `short_rate` is the 13-week T-bill (`^IRX`) and `α` is a single constant
(**~1.26%/yr**) calibrated so the synthetic's total return matches **real** TQQQ over
2010–2026 (the index is price-only, so α mainly absorbs the 3× dividend yield).

- Daily-return correlation vs real TQQQ, 2010–2026: **~0.999**.
- Pricing-vol input: `^VXN` (from 2001), `^VIX × 1.15` before it — which bounds the
  window on the left at **1990** (VIX's inception). Options models cannot go earlier
  without a synthetic realized-vol proxy.

## Results (1990-06-29 → 2026-08-14, ~9,100 days)

*`DD 1990 / dot-com / 2008` are drawdowns within those crash windows. **The dot-com
column is measured from the March-2000 peak** — an earlier version started this run
at 2001-06, which began* after *the initial crash and so understated it.*

| Model | CAGR | Max DD | Sharpe | Calmar | DD 1990 | DD dot-com | DD 2008 |
|---|--:|--:|--:|--:|--:|--:|--:|
| Buy & Hold TQQQ | 15.1% | **~-100%** | 0.52 | 0.15 | -73% | -100% | -95% |
| Trend (no options) | 88.6% | -53.6% | 1.49 | 1.65 | -33% | -54% | -25% |
| Covered Calls | 77.6% | -54.6% | 1.56 | 1.42 | -30% | -55% | -22% |
| Two-Sided Dynamic | 89.9% | -74.2% | 1.43 | 1.21 | -31% | -74% | -27% |
| **Collar (P.15)** | 83.2% | -26.5% | 2.01 | **3.14** | -23% | -26% | -14% |
| **Collar (P.20)** | 80.2% | -22.6% | 2.08 | **3.55** | -22% | -20% | -12% |

## What it shows

1. **The strategy rests on trend-following, not options.** A 3× Nasdaq ETF held
   from the March-2000 peak is a **~total wipeout** (Buy & Hold ≈ -100%). The SMA200
   cash-rotation is what makes leveraged Nasdaq survivable at all; options are a
   second-order refinement on top.
2. **The fast April-2000 dot-com crash is the true worst case, and only the collar
   survives it.** That crash fell ~35% in weeks — too fast for a 200-day average to
   dodge — so plain Trend still takes **-54%**. **Covered calls take -55% right
   beside it** (a premium cushion is useless against a move that size), dropping
   their Calmar to **1.42, *below* Trend's 1.65**. The two-sided engine is worst
   (-74%; its short puts get run over). **Only the collar's protective put contains
   the crash** (-26% / -20%) — so it is the *only* overlay that beats plain Trend
   over the full history (Calmar 3.1–3.6). The collar's edge is structural
   (self-financing → vol-robust; the put's protection is mechanical), not fitted.
3. **This corrects the earlier (2001-start) read.** Covered calls appeared to be a
   *runner-up* over 2018–2026 and any 2001-start window — but those windows were
   crash-light or began *after* the March-2000 crash, so they never tested downside
   protection against a fast leveraged crash. Extending the backtest before 2000 is
   what separates the collar (real put) from the covered call (premium only).

## Caveats — read before quoting

- **Pre-2010 TQQQ is reconstructed, not real** (validated at ~0.999 daily
  correlation, but still a model). Pre-2001 vol uses a `^VIX × 1.15` proxy.
- **Ignore the absolute ending dollars.** Decades of frictionless ~80% CAGR compound
  to absurd levels no real account reaches (capacity, slippage, taxes, and the
  model's other simplifications are absent). Trust the **path, drawdowns,
  Sharpe/Calmar, and cross-strategy ranking** — not the totals.
- Option pricing still assumes vol = `^VXN × 2.5` and a fixed 1.2× put skew.
- Single historical path; the collar's advantage is largest when crashes actually
  occur (which, across 1990–2026, they did — four times).
