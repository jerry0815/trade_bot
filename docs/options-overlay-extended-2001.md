# Extended backtest — reconstructed TQQQ, 2001–2026

Real TQQQ began 2010-02-11, so the primary benchmark
(`docs/options-overlay-benchmark.md`, 2018–2026) never saw a prolonged bear. This
run rebuilds a **synthetic TQQQ** from `^NDX` (history to 1985) and stress-tests the
strategies through the **dot-com collapse** and **2008** — the regimes that matter
most for a 3× leveraged product. See `options/reconstruct_tqqq.py`.

## Reconstruction & validation

Synthetic daily return = `3 × r_NDX − (0.95% expense + 2 × short_rate) / 252 + α`,
where `short_rate` is the 13-week T-bill (`^IRX`) and `α` is a single constant
(**1.26%/yr**) calibrated so the synthetic's total return matches **real** TQQQ over
2010–2026 (the index is price-only, so α mainly absorbs the 3× dividend yield).

- Daily-return correlation vs real TQQQ, 2010–2026: **~0.999**.
- Pricing-vol input: `^VXN` (from 2001), `^VIX × 1.15` before it.

## Results (2001-06-01 → 2026-08-14, 6,338 days)

| Model | CAGR | MaxDD | Sharpe | Calmar | DD dot-com | DD 2008 |
|---|--:|--:|--:|--:|--:|--:|
| Buy & Hold TQQQ | 13.6% | **−98.6%** | 0.48 | 0.14 | −96.9% | −95.0% |
| Trend (no options) | 75.9% | −33.4% | 1.52 | 2.27 | −20.7% | −24.7% |
| Covered Calls | 77.3% | −27.4% | 1.72 | 2.82 | −16.5% | −21.7% |
| Collar P.15 | 75.7% | −22.4% | 2.14 | 3.38 | −14.9% | −13.9% |
| Collar P.20 | 71.8% | −20.2% | 2.20 | 3.56 | −14.2% | −12.4% |

## What it shows

1. **The strategy rests on trend-following, not options.** A 3× Nasdaq ETF held
   through the dot-com crash draws down **−98.6%** — a near-total wipeout. The
   SMA200 cash-rotation cuts that to −33%. Options are a second-order refinement;
   the trend rule is what makes leveraged Nasdaq survivable at all.
2. **The collar's edge holds up across four bears, and is largest in the worst
   ones.** In 2008 it cut drawdown to −12% vs Trend's −25%. The 2018–2026 window
   couldn't test the "does the protective put earn its keep in a real crash?"
   question; here it clearly does. The Calmar ranking is preserved:
   Collar > Covered Calls > Trend > Buy & Hold.
3. **A fast crash hurts a trend-follower more than a slow bear.** For every
   trend-based model the *overall* MaxDD above is the **2020 COVID crash**, not
   dot-com or 2008 — which is why the overall MaxDD matches the 2018–2026 primary
   benchmark almost exactly (that event lives in both windows). Dot-com and 2008
   declined over months, so the SMA200 rule rotates to cash early and the
   drawdowns are *shallower* (−16% to −25%); COVID fell ~35% in three weeks,
   faster than a 200-day average can react, so the strategy ate the first hit and
   got whipsawed on the V-recovery. Only Buy & Hold, which never rotates, has its
   worst drawdown in the slow bears (the full −98.6% leveraged wipeout in 2008).
   The new pre-2010 data is therefore exercised by the **dot-com / 2008 columns**,
   not the overall MaxDD.

## Caveats — read before quoting

- **Pre-2010 TQQQ is reconstructed, not real** (validated at ~0.999 daily
  correlation, but still a model). Pre-2001 vol uses a `^VIX × 1.15` proxy.
- **Ignore the absolute ending dollars.** 25 years of frictionless ~75% CAGR
  compounds to absurd levels no real account reaches (capacity, slippage, taxes,
  and the model's other simplifications are not present). Trust the **path,
  drawdowns, Sharpe/Calmar, and cross-strategy ranking** — not the totals.
- Option pricing still assumes vol = `^VXN × 2.5` and a fixed 1.2× put skew.
- Single historical path; the collar's advantage is largest when crashes actually
  occur (which, across 2001–2026, they did — four times).
