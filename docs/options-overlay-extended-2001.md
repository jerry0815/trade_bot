# Extended backtest — reconstructed TQQQ, 1990–2026

Real TQQQ began 2010-02-11, so the primary benchmark
(`docs/options-overlay-benchmark.md`, 2018–2026) never saw a prolonged bear. This
run rebuilds a **synthetic TQQQ** from `^NDX` (history to 1985) and stress-tests the
strategies through **four** major bears — the 1990 Gulf-War recession, the
**dot-com collapse**, **2008**, and 2022. See `options/reconstruct_tqqq.py`.

> ⚠️ **T+1 execution correction.** An earlier version sized each day's return with
> that day's close (a 1-day lookahead) which inflated every trend-based CAGR ~4×.
> The engine now uses next-day execution; the numbers below are realistic and in
> the same range as the production engine.

## Reconstruction & validation

Synthetic daily return = `3 × r_NDX − (0.95% expense + 2 × short_rate) / 252 + α`,
`α` (~1.26%/yr) calibrated so total return matches **real** TQQQ over 2010–2026.

- Daily-return correlation vs real TQQQ, 2010–2026: **~0.999**.
- Pricing-vol input: `^VXN` (from 2001), `^VIX × 1.15` before it — which bounds the
  window on the left at **1990** (VIX's inception).

## Results (1990-06-29 → 2026-08-14, ~9,100 days)

*`DD 1990 / dot-com / 2008` are drawdowns within those crash windows; **dot-com is
measured from the March-2000 peak**.*

| Model | CAGR | Max DD | Sharpe | Calmar | DD 1990 | DD dot-com | DD 2008 |
|---|--:|--:|--:|--:|--:|--:|--:|
| Buy & Hold TQQQ | 17.9% | **~-100%** | 0.55 | 0.18 | -72% | -100% | -95% |
| Trend (no options) | 24.5% | -66.7% | 0.61 | 0.37 | -32% | -65% | -49% |
| Covered Calls | 17.0% | -64.5% | 0.48 | 0.26 | -28% | -65% | -44% |
| Two-Sided Dynamic | 23.5% | -84.9% | 0.59 | 0.28 | -33% | -85% | -52% |
| **Collar (P.15)** | 20.4% | -45.9% | **0.62** | **0.45** | -24% | -42% | -34% |
| **Collar (P.20)** | 18.9% | -43.3% | 0.60 | 0.44 | -24% | -37% | -33% |

## What it shows

1. **Trend-following makes leveraged Nasdaq survivable in *sustained* bears.** A 3×
   Nasdaq ETF held from the March-2000 peak is a ~total wipeout (Buy & Hold ≈ -100%,
   Calmar 0.18); the SMA200 cash-rotation lifts Calmar to 0.37 by rotating out of
   the dot-com and 2008 grinds. (Over the V-shaped 2018–2026 window, by contrast,
   Buy & Hold beats this simple trend rule — trend-following needs a real bear.)
2. **The collar is the best overlay, via drawdown protection.** Only its protective
   put contains the fast April-2000 crash (-42% vs -65% to -100%) and 2008 (-34% vs
   -49%), giving the best Calmar (0.44–0.45) and Sharpe (0.60–0.62). **Covered calls
   draw down -65% right alongside plain Trend** — a premium cushion is useless
   against a crash that size — so they are the *worst* overlay (Calmar 0.26). The
   two-sided engine is worse still (-85%; its short puts get run over).
3. **The edge is modest and the trend rule is weak.** These are realistic numbers
   (Calmar 0.2–0.45, not the earlier lookahead-inflated 2–4). And the sleeve is a
   naive single-signal SMA200 — the production bot's dual-signal + trailing-stop is
   stronger, so "collar helps this sleeve" does not automatically transfer to it.

## Caveats — read before quoting

- **Pre-2010 TQQQ is reconstructed** (validated at ~0.999 daily correlation, but a
  model). Pre-2001 vol uses a `^VIX × 1.15` proxy.
- **Ignore the absolute ending dollars** — frictionless compounding. Trust the
  path, drawdowns, Sharpe/Calmar, and cross-strategy ranking.
- Option pricing assumes vol = `^VXN × 2.5` and a fixed 1.2× put skew.
- Single historical path; the collar's advantage is largest when crashes occur
  (1990–2026 had four). For the robust rolling-window view see the [strategy
  doc](strategies/options-overlay.md) Table 11.
