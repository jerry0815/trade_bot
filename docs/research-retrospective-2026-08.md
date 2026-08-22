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
- **A dynamic 3-gear leverage rule (screened, not confirmed) is no exception.**
  Reusing the same SMA+ATR bands to drive a reduced-leverage middle gear instead of
  binary in/out beat neither baseline on Calmar or Sharpe, and deepened the worst
  drawdown. **Screen negative — confirm stage not run.** See §7.
- **Vol-targeted up-scaling past 3× is refuted, not just neutral (screened).**
  Letting the same signal's in-market state size up to a 4×/5× cap via a
  vol-target rule *worsens* Calmar and Sharpe monotonically as the cap rises, and
  the down-only (cap 3×) variant that does look best on Calmar still trails fixed
  2× on Sharpe. **Screen negative — confirm stage not run.** See §8.

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

## 7. Dynamic-leverage 3-gear (negative screen)

A separate idea: keep the existing SMA+ATR band signal but stop treating its
neutral zone as "hold prior position." Instead, map the same three band states to
three fixed exposures — 3× above the upper band, cash below the lower band, and a
defined **middle gear** inside the band — and sweep the middle gear over {1.0×,
1.5×, 2.0×}. The only behavioral change versus the binary rule is removing that
neutral-zone hysteresis in favor of an explicit reduced-leverage sleeve.

**Screen (1990–2026, single-signal ^NDX sleeve, pre-tax, frictionless):**

| Strategy | CAGR | Worst DD | Calmar | Sharpe | Trades | Rebal |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Binary 3x (baseline) | 25.49% | -81.37% | 0.31 | 0.68 | 20 | 0 |
| Fixed 2x (same signal) | 21.93% | -62.49% | 0.35 | 0.71 | 20 | 0 |
| 3-Gear (mid 1.0x) | 19.07% | -88.55% | 0.22 | 0.60 | 111 | 374 |
| 3-Gear (mid 1.5x) | 20.34% | -90.87% | 0.22 | 0.62 | 111 | 374 |
| 3-Gear (mid 2.0x) | 21.04% | -93.35% | 0.23 | 0.63 | 111 | 374 |

No middle gear beats *either* baseline on Calmar or Sharpe (0.22–0.23 vs 0.31 /
0.35 Calmar; 0.60–0.63 vs 0.68 / 0.71 Sharpe) — fixed 2× remains the risk-adjusted
winner. This is the same standing conclusion as §1: leverage **tier** is the
load-bearing lever, not signal cleverness, and turning the same signal into a
finer-grained rule doesn't change that.

The deeper drawdown is the more interesting (and counterintuitive) part. Binary 3×
holds a position until the signal flips and simply sits out the rest — 20 trades,
zero rebalances. Removing the hysteresis means the rule re-levers to the middle
gear the moment price ticks back above the lower band, even inside a choppy
bottoming process — 111 trades and 374 rebalances. Each of those re-entries buys
leveraged exposure mid-decline, so the "middle gear" doesn't cushion the drawdown,
it bleeds through the transition zone, repeatedly re-adding risk before the
downtrend is actually over. That mechanism, not the lower nominal leverage, is why
every middle-gear row draws down *more* than the all-or-nothing binary rule.

This is a **single-path, frictionless screen**, not a headline. Per the staged
plan, the rolling-window + reconstruction confirm stage is gated on the screen
clearing the bar (§5 of the plan) — it did not, so that stage was **not run**.
See [`backtest/dynamic_leverage_screen_output.md`](../backtest/dynamic_leverage_screen_output.md)
for the raw output and [`backtest/dynamic_leverage_screen.py`](../backtest/dynamic_leverage_screen.py)
for the reproducing script.

## 8. Vol-targeted leverage — up-scaling (negative screen)

A further idea, distinct from §7: instead of a discrete middle gear, size the
in-market state continuously by realized volatility — `min(l_max, target_vol /
realized_vol)` — and ask whether allowing the cap above 3× (the production tier)
finds any exposure schedule that beats both baselines.

**Screen (1990–2026, single-signal ^NDX sleeve, pre-tax, frictionless):**

| Strategy | CAGR | Worst DD | Calmar | Sharpe | Avg Lev | Trades | Rebal |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Binary 3x (baseline) | 25.49% | -81.37% | 0.31 | 0.68 | — | 20 | 0 |
| Fixed 2x (same signal) | 21.93% | -62.49% | 0.35 | 0.71 | — | 20 | 0 |
| VolTarget (cap 3x) | 21.07% | -56.94% | 0.37 | 0.68 | 2.43x | 20 | 4308 |
| VolTarget (cap 4x) | 21.25% | -62.10% | 0.34 | 0.67 | 2.66x | 20 | 5884 |
| VolTarget (cap 5x) | 21.34% | -65.54% | 0.33 | 0.67 | 2.74x | 20 | 6393 |

No row beats *both* baselines on *both* Calmar and Sharpe — **screen negative.**

1. **Up-scaling (>3×) is refuted, not merely neutral.** Raising the cap 3→4→5
   *monotonically worsens* risk-adjusted metrics (Calmar 0.37→0.34→0.33; Sharpe
   0.68→0.67→0.67) and deepens the worst drawdown (−57%→−62%→−66%). It also barely
   activates — average leverage rises only 2.43→2.66→2.74× — because at a sane
   `target_vol` (45%) the >3× regime only triggers on rare ultra-calm days, and
   ultra-calm days tend to precede volatility expansions. The rule levers up right
   before turbulence, the classic vol-target-at-the-top failure. The one
   genuinely untested dynamic-leverage direction does not beat the baseline.
2. **The down-only variant (cap 3×) is the familiar near-neutral, with a
   friction-fragile catch.** It posts the best Calmar (0.37) and shallowest
   drawdown (−57%) in the table — genuinely better drawdown control than fixed
   2× — but its Sharpe (0.68) still trails fixed 2× (0.71), so it fails the
   both-metrics bar. That drawdown edge rode on 4,308 rebalances (near-daily
   churn) vs. 0 for both static strategies; frictionless, that's free, but
   transaction costs and short-term-gains tax on daily rebalancing would very
   likely erase the edge. This is why the screen is a **soft upper bound** and any
   confirm stage would have to model friction before the number means anything.
3. **Same standing conclusion as §1 and §7.** Fixed 2× remains the best
   all-around risk-adjusted choice; the load-bearing lever is the static
   leverage *tier*, not a time-varying rule. This closes the dynamic-leverage
   thread: vol-targeting neutral, 3-gear worse, up-scaling refuted.

Per the staged plan, the friction-aware confirm stage is gated on the screen
clearing the Calmar-AND-Sharpe bar (§4/§6 of the plan) — it did not, so that stage
was **not run**. See [`backtest/vol_target_screen_output.md`](../backtest/vol_target_screen_output.md)
for the raw output and [`backtest/vol_target_screen.py`](../backtest/vol_target_screen.py)
for the reproducing script.
