# Options Overlay (negative result — not adopted)

[← Back to README](../../README.md) · Related: [Methodology](methodology.md) · [Core Trend Signal](core-trend-signal.md)

A research overlay that layered an options structure (covered call, collar, protective put, or a two-sided premium engine) on top of the leveraged (3× TQQQ) trend sleeve, in a self-contained [`options/`](../../options/) package. **Conclusion: none of them beat running the trend rule bare.** Two backtesting bugs made earlier drafts of this doc claim a collar "won"; once both are fixed, the overlay provides **no robust benefit** and most variants are net-destructive. It is **not** part of the production `bot.py` recommendation and should not be executed.

---

## Bottom line

Correctly priced, **no options overlay beats the bare trend rule at any strike, on either the simple single-signal sleeve or the production dual-signal + trailing-stop allocation.** Covered calls cap upside for too little; buying protection bleeds more premium than its crash payoffs recover; the collar combines both into a net loss.

| 1990–2026, Calmar (CAGR/MaxDD) | Bare Trend | Covered Calls | Collar (P.15) | Put-only (P.15) |
| :--- | ---: | ---: | ---: | ---: |
| Single-signal sleeve | **0.35** | 0.16 | −0.02 | 0.06 |
| Production sleeve (dual-signal + stop) | **0.47** | 0.18 | −0.01 | 0.14 |

Nothing improved at other strikes (0.20Δ / 0.30Δ were worse on both sleeves). The collar's max drawdown was *deeper* than doing nothing (−81% to −99% vs trend's −61%): the fairly-priced protective put grinds the book down with premium bleed faster than it recovers in crashes. **Verdict: dropped as an execution candidate.**

---

## Why earlier drafts were wrong

This overlay looked good until two backtesting bugs were found and fixed:

1. **1-day lookahead in the equity sleeve.** The engine sized each day's return with *that day's* close (next-day execution avoids this). It inflated every trend-based CAGR ~4× (Trend 88% → 22%). Fixed to T+1.
2. **Strike-selection vs pricing vol mismatch.** Each option's strike was chosen at the *base* vol but priced/marked at the *skewed* vol. For a bought put that's a free lunch — the "15Δ" put was actually struck closer to spot (more protective) *and* marked at inflated vol. The tell: making puts **more expensive** (raising the put skew) *improved* a put-*buying* strategy — impossible if the model were consistent. Fixed so each strike is selected at the same skew-adjusted vol it is priced at.

The collar's apparent edge (a headline Calmar of ~0.6, and inflated drafts as high as ~4) came almost entirely from bug #2. With genuine 15Δ puts priced fairly, that edge is gone.

## What still holds

- **Trend-following is the load-bearing layer**, and the production dual-signal + trailing-stop rule is genuinely stronger than a naive single-signal SMA200 (Calmar 0.47 vs 0.35 over 1990–2026). That result is unaffected by the option bugs and stands.
- Covered calls hurt a leveraged trend-follower (they were the worst overlay in every consistent run) — you're short exactly the fat-right-tail convexity that makes the strategy work.

## Caveats on the negative result

- These are frictionless, single-path, reconstructed-data results; the *magnitudes* are approximate. But the *ranking* — every overlay below bare trend — is consistent across sleeves, strikes, and crash windows, and the sign is robust.
- A live-chain snapshot (2026) validated the core pricing: real ATM TQQQ IV ≈ 2.53× VXN vs the model's 2.50×; real ~15Δ put ≈ 3.31× VXN (the model's 3.0× is if anything slightly generous to the put buyer, so correct pricing makes the overlay *worse*, not better).

## Further reading

- [Options overlay benchmark (2018–2026)](../options-overlay-benchmark.md) — corrected 4-model table.
- [Extended reconstruction backtest (1990–2026)](../options-overlay-extended-2001.md) — the four-bear stress test behind the numbers above.
- [`options/README.md`](../../options/README.md) — engine, models, and how to reproduce.
