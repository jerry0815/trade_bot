# Research retrospective — options overlay & trend optimization (Aug 2026)

[← Back to README](../README.md)

A consolidated record of an extended research push: can the leveraged (3× TQQQ)
trend strategy be improved, either by an **options overlay** or by **optimizing the
trend rule itself**? The short answer is **no** — every avenue tried lands at or
below simply running the production trend rule. This doc elaborates what was tried,
what was found, the two backtesting bugs that nearly produced false positives, and
the lessons. The production strategy is unchanged; the `options/` package is retained
as a documented negative finding, not an execution candidate.

---

## 1. Bottom line

- **No options overlay beats the bare trend rule.** Covered calls, a two-sided
  premium engine, a protective-put hedge, a collar, and a put-only structure were
  all tested. Correctly priced, every one trails the trend rule at every strike, on
  both a simple single-signal sleeve and the production dual-signal + trailing-stop
  allocation. The collar is net-negative. **Dropped.**
- **The trend rule is already near its practical optimum.** EMA-vs-SMA signal choice
  is ~neutral; volatility-targeted position sizing is ~neutral (it is redundant with
  a trend rule that already exits high-vol regimes). Further threshold tuning is
  overfitting.
- **The only lever that meaningfully moves the deep drawdowns is leverage itself**
  (2× roughly halves the worst-case drawdown for a modest return give-up — already
  quantified in the leverage-tier tables). Signal cleverness does not.

---

## 2. The options overlay — what was tried

A self-contained [`options/`](../options/) event-driven engine layered structures on
the trend sleeve (see [`options/README.md`](../options/README.md) for the models):

| Structure | Idea | Verdict |
|---|---|---|
| Static covered calls | Sell ~20Δ calls in the bull regime | Hurts — caps the fat right tail trend-following depends on |
| Two-sided dynamic engine | IV-gated CC / CSP / bull-put / put-debit | Worst — short puts add left-tail risk |
| Protective-put hedge (`hedge_only`) | Buy a put-debit spread as insurance | Bleeds; doesn't beat trend |
| Collar | Sell ~20Δ call to finance a ~15Δ put | Net-negative once priced correctly |
| Put-only (`protective_put`) | Drop the short call, keep the put | Below trend; a bought-vol bet |

**Corrected results (1990–2026, vol-consistent), Calmar (CAGR/MaxDD):**

| Sleeve | Bare Trend | Covered Calls | Put-only | Collar |
|---|--:|--:|--:|--:|
| Single-signal | **0.35** | 0.16 | 0.06 | −0.02 |
| Production (dual-signal + stop) | **0.47** | 0.18 | 0.14 | −0.01 |

---

## 3. The two bugs that nearly produced false positives

Early drafts of this work confidently concluded "a collar wins" (with Calmars as
high as ~4). That was wrong, caused by two backtesting bugs found only through
skeptical, repeated validation:

1. **1-day equity-sleeve lookahead.** The engine sized each day's return with *that
   day's* close instead of the prior close (next-day execution). It inflated every
   trend-based CAGR ~4× (Trend 88% → 22%). Caught by comparing to the production
   engine's realistic ~23%. Fixed to T+1.
2. **Strike-selection vs pricing vol mismatch.** Each option's strike was chosen at
   the *base* vol but priced/marked at the *skew-adjusted* vol, handing a bought put
   value its delta never paid for. The tell was diagnostic: **raising the put skew
   (making puts more expensive) *improved* a put-buying strategy** — impossible in a
   consistent model. Fixed so each strike is selected at the vol it is priced at.

A live TQQQ option-chain snapshot (2026) validated the surviving pricing: real ATM
IV ≈ 2.53× VXN vs the model's 2.50×; real ~15Δ put ≈ 3.31× VXN (the model's 3.0× is
if anything generous to the put buyer).

## 4. Optimizing the trend rule — what was tried

- **EMA 50/200 vs SMA 200 signal:** ~neutral in practice (a signal wearing different
  clothes; the repo's global-equities table had hinted EMA led, but it did not
  meaningfully move the production rule).
- **Volatility-targeted sizing:** hold `min(1, target_vol / realized_vol)` of the
  book in TQQQ when in-market. **Neutral on both eras** — Sharpe 0.66–0.68 vs 0.67
  (1990–2026 and 2010+). Why: high vol and downtrends are correlated, so by the time
  vol spikes enough to cut exposure, the dual-signal + 8% stop has usually *already*
  rotated to cash. Vol management helps portfolios that stay invested *through*
  turbulence; a trend rule that goes to cash has already banked that benefit.

## 5. Lessons

- **A backtest result that improves when you make a bought instrument more expensive
  is a red flag** — it means the pricing model is internally inconsistent. Sanity
  checks like this catch artifacts that impressive tables hide.
- **Single-path, frictionless backtests inflate.** Hold every new idea to
  out-of-sample validation (both the reconstruction and the real-data era), the
  production engine as a reality check, and the burden of proof on the *new* idea.
- **Redundancy is the quiet killer of "improvements."** Both vol-targeting and the
  options overlay largely duplicated protection the trend rule already provides, so
  their marginal value was near zero even where the mechanism was sound.
- **A well-tuned optimum is a valid finding.** "Nothing beat the baseline" is a
  result, not a failure — it says the production strategy is already good and the
  remaining trade-off is structural (leverage), not a missing signal.

## 6. What changed in the repo

- Options overlay: **dropped as an execution candidate.** The `options/` research
  package and its docs are retained as a documented negative finding; the live
  collar monitor and its scheduled workflow were **removed**.
- Trend strategy: **unchanged.** The production dual-signal + 8%/60d trailing-stop
  rule (with defensive rotation) stands as the recommendation.
