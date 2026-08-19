# Extended backtest — reconstructed TQQQ, 1990–2026 (negative result)

Real TQQQ began 2010-02-11, so the 2018–2026 benchmark never saw a prolonged bear.
This run rebuilds a **synthetic TQQQ** from `^NDX` (history to 1985) and stress-tests
the strategies through four major bears — the 1990 recession, dot-com, 2008, and
2022. **Conclusion: no options overlay beats the bare trend rule.** See
`options/reconstruct_tqqq.py`.

> ⚠️ Two backtesting bugs (a 1-day sleeve lookahead and a strike-selection-vs-pricing
> vol mismatch) inflated earlier drafts. Both are fixed; the engine now uses
> next-day (T+1) execution and selects each option strike at the same skew-adjusted
> vol it is priced at. Numbers below are the corrected ones. See the
> [strategy doc](strategies/options-overlay.md#why-earlier-drafts-were-wrong).

## Reconstruction & validation

Synthetic daily return = `3 × r_NDX − (0.95% expense + 2 × short_rate)/252 + α`,
`α` (~1.26%/yr) calibrated so total return matches real TQQQ over 2010–2026.
Daily-return correlation vs real TQQQ: **~0.999**. Pricing vol = `^VXN × 2.5`
(`^VIX × 1.15` before 2001), validated against a live chain (real ATM IV ≈ 2.53× VXN).

## Results (1990-06-29 → 2026-08-14, single-signal sleeve, vol-consistent)

| Model | CAGR | Max DD | Calmar |
|---|--:|--:|--:|
| Buy & Hold TQQQ | 17.9% | ~-100% | 0.18 |
| **Trend (no options)** | **22.8%** | -65.4% | **0.35** |
| Covered Calls | 10.2% | -65.4% | 0.16 |
| Put-only (P.15) | 5.0% | -83.2% | 0.06 |
| Collar (P.15) | -1.7% | -92.8% | -0.02 |

Every overlay lands **below bare Trend**, at every strike tested (0.15/0.20/0.30Δ),
on both this single-signal sleeve and the production dual-signal + trailing-stop
allocation (Trend 0.47 there; all overlays ≤ 0.18). The same ordering holds in the
2018–2026 benchmark. The overlays' drawdowns are *deeper* than doing nothing — a
fairly-priced protective put grinds the book down with premium bleed faster than it
recovers in crashes.

## What it shows

1. **Trend-following makes leveraged Nasdaq survivable in sustained bears** (Buy &
   Hold ≈ −100% through dot-com; Trend rotates to cash and holds a positive Calmar).
   The production dual-signal + trailing-stop rule is stronger still (Calmar 0.47).
   These results are unaffected by the option bugs and stand.
2. **Options add nothing here.** Covered calls cap the fat-right-tail convexity that
   makes leveraged trend-following work; bought protection bleeds more than it saves;
   the collar nets to a loss. Earlier "collar wins" drafts were a pricing artifact.

## Caveats

- Pre-2010 TQQQ is reconstructed (validated ~0.999 daily correlation, but a model).
- Frictionless, single-path; treat magnitudes as approximate. The *ranking* (every
  overlay below bare trend) is robust across sleeves, strikes, and crash windows.
