# Design — Vol-Targeted Leverage (up-scaling)

**Date:** 2026-08-21
**Status:** design approved, spec under review
**Author:** Claude Code (with Jerry)
**Related:** [research-retrospective-2026-08.md](../../research-retrospective-2026-08.md) · [2026-08-21-dynamic-leverage-3gear-design.md](2026-08-21-dynamic-leverage-3gear-design.md) · [strat_backtest.py](../../../backtest/strat_backtest.py)

---

## 1. Motivation

The dynamic-leverage thread has one untested direction left. Everything tried so far only ever
scaled leverage **down**: volatility-targeted sizing (neutral — redundant with the cash
rotation) and the 3-gear (worse — whipsaw in the transition band). Both duplicate protection
the trend rule already provides. The one direction the trend rule does **not** already cover is
scaling leverage **up** in the calmest strong uptrends — the "leverage for the long run" /
Kelly idea: optimal leverage scales inversely with variance, so when realized vol is unusually
low, a higher-than-3× exposure may be warranted.

The bar is **fixed 2×**, the risk-adjusted winner of the 3-gear screen (Calmar 0.35, Sharpe
0.71) — not binary 3×. And the burden of proof is on this idea; the prior is "static tier is
the lever."

## 2. The rule — `VolTargetLeverage`

**Keep the binary trend rule's entry/exit exactly.** This is the deliberate fix for the
3-gear's mistake: do not touch the regime decision (in vs. out), only the leverage *while
in-market*. The strategy **subclasses `SMATrendFollowing`** and reuses its `in_market` column
verbatim (`Close > SMA200 + 2.5·ATR` bull-entry, `< SMA − 2.5·ATR` bear-exit, hysteresis in the
band — already `.shift(1)` for next-day execution, [strat_backtest.py:641](../../../backtest/strat_backtest.py)).

Where in-market, size leverage by target volatility:

```
L_t = clamp( target_vol / realized_vol_t , L_min , L_max )
```

Where out-of-market → `target_leverage = 0` (cash). The hard crash exit stays.

- `realized_vol_t` = trailing 20-day annualized vol of the **unleveraged** ^NDX
  (`Close.pct_change().rolling(20).std() * sqrt(252)`), **shifted one day** so day `t`'s
  leverage uses only returns through `t−1`. Combined with the already-shifted `in_market`, the
  rule is lookahead-free.
- Parameters: `target_vol=0.45` (fixed, untuned — maps ~18% realized vol to ≈2.5×), `l_min=1.0`,
  `l_max` (swept), `vol_window=20`, `atr_multiplier=2.5`.

**The sweep:** fix everything, sweep **`L_max ∈ {3×, 4×, 5×}`**.
- `L_max=3×` is the **down-only ablation** — it should reproduce the known "neutral" vol-target
  result and anchors the comparison.
- `L_max=4×, 5×` **permit up-scaling** in calm regimes — the actual open question.

## 3. Engine — no change except one reporting metric

The engine already consumes a per-day `target_leverage` column and its drag/return math already
generalizes to `L>3` (`drag = ((L−1)·BR + expense)/252`; the four day-type formulas). No engine
logic change.

**One additive, reporting-only change:** `_calculate_trade_stats` gains an `avg_leverage` key
(mean of `target_leverage` over in-market days; `NaN`/`0` when the column is absent), parallel to
the existing `rebalances` metric, so the screen table can show how much leverage each config
actually used. Backward-compatible by construction (guarded on the column's presence).

## 4. Baselines & success bar

- **Binary 3×** (`SMATrendFollowing` at leverage 3) and **fixed 2×** (same signal at leverage 2)
  — identical to the 3-gear screen, so the two screens are directly comparable.
- **Success = Calmar AND Sharpe above BOTH baselines** by a real margin. Requiring both metrics
  is what stops "5× just adds return with proportional risk" (a slide along the same risk/return
  line) from reading as a win — its Calmar/Sharpe would not exceed 2×'s.

## 5. Metrics reported

Per config: CAGR, worst DD, Calmar, Sharpe, **avg leverage**, **rebalances**, trades. Avg
leverage and rebalances make the turnover and the actual leverage used visible — central to
judging realism.

## 6. Validation — staged; the screen is a soft UPPER bound

Single continuous **1990–2026** path, single-signal ^NDX sleeve, pre-tax, **frictionless**, as a
screen. **Critical framing:** vol-targeting re-levers *every day* (~250 rebalances/yr). A
frictionless model charges nothing for that, which **flatters this strategy more than any other
tested** — so even a screen *win* is only a soft upper bound. Escalate to the confirm stage
**only if** a cap beats both baselines on Calmar and Sharpe by a real margin; the confirm stage
must add **transaction-cost + tax friction on the daily rebalancing**, not just rolling windows,
because friction is the thing most likely to erase a vol-target edge. If the screen is negative,
document and stop.

## 7. Realism caveats (state alongside any result)

- **Daily rebalancing turnover** (see §6) — the dominant caveat; the frictionless number is an
  optimistic ceiling.
- **>3× is not an ETF** — needs margin/futures/options; financing above broker thresholds is
  higher and path-dependent than the linear borrow drag models.
- **No margin-call liquidation** is modeled — at 5×, a ~−20% single-day index move mathematically
  wipes the book, and even smaller drops that a real margin account would liquidate are allowed
  to "recover" in the model. ^NDX's worst single days (~−10 to −12%) don't trigger this at ≤5×,
  but the absence of a liquidation floor still flatters high-leverage configs in fast crashes.
- Single-path, frictionless, reconstructed-data — magnitudes approximate; only the ranking vs
  baselines is load-bearing, and only after the friction-aware confirm.

## 8. Out of scope

- The friction-aware / rolling confirm stage (gated on a screen win).
- Sweeping `target_vol` or `vol_window` (fixed to limit overfit surface; note sensitivity only if
  results are borderline).
- Any change to the production `bot.py` recommendation, or to `SMATrendFollowing`'s own logic
  (subclass only, reuse `in_market` unmodified).
- Options, the 3-gear, and continuous/bucketed leverage (closed/parked).

## 9. Deliverables

- `VolTargetLeverage` strategy (subclass of `SMATrendFollowing`) + unit tests (network-free).
- The `avg_leverage` reporting metric + its test.
- A screen script (`backtest/vol_target_screen.py`) reusing the existing `calmar` /
  `sharpe_from_equity` helpers, producing the 1990–2026 KPI table.
- A finding — folded into the retrospective if negative; its own doc + README row only if a cap
  produces a genuine win that survives the (later, gated) friction-aware confirm.
