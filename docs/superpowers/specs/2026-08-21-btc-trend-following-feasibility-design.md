# Design — Bitcoin Trend-Following Feasibility Study

**Date:** 2026-08-21
**Status:** design approved, spec under review
**Author:** Claude Code (with Jerry)
**Related:** [methodology.md](../../strategies/methodology.md) · [core-trend-signal.md](../../strategies/core-trend-signal.md) · [trailing-stop.md](../../strategies/trailing-stop.md) · [research-retrospective-2026-08.md](../../research-retrospective-2026-08.md) · [strat_backtest.py](../../../backtest/strat_backtest.py)

---

## 1. Motivation & goal

Can the project's equity trend-following rule (SMA 200 + ATR buffer, optionally a trailing
stop) be shown to work on Bitcoin? Spot BTC has ~60–80% annualized volatility — roughly 3–4×
the NASDAQ — so it behaves almost like an already-leveraged asset, and its 70–85% bear
drawdowns are exactly the "clip the left tail" failure mode the trend rule targets. On its face
it's a natural fit.

The blocker is **history**. The equity results earn credibility from *172 monthly-stepped
26-year windows*, each forced through the dot-com crash, 2008, COVID, and 2022. BTC has ~11
years of usable daily data and only **~3 independent drawdown cycles** (2014–15, 2018, 2021–22),
which are largely one repeated pattern (parabolic run → deep bear, loosely halving-tied). That
window-count credibility engine is physically unavailable here.

**Goal — feasibility study (honest yes / no / inconclusive).** The primary deliverable is a
*credible verdict on whether trend-following transfers to BTC*, where **"inconclusive — the data
cannot separate it from luck"** is a fully acceptable, shippable outcome (as with the options
overlay, EMA, and vol-targeting negatives already in the repo). Only **if it survives** do we
escalate: comparative cross-checks, then a potential production sleeve. Those escalations are
**out of scope** for this spec.

**Scope this study is deliberately NOT:** not a production bot change; not a leveraged-BTC
study (spot 1× only — leverage is a follow-on *if* the signal survives on spot); not a
parameter search for the "best BTC rule" (see §4 — the whole point is *no* BTC tuning).

## 2. The central methodology decision — where credibility comes from

**The trap we explicitly refuse:** running "rolling 5-year windows stepped monthly" on ~11
years of BTC would manufacture 80+ windows that all share the same 3 drawdown cycles. The window
count would be *cosmetic* — essentially one path wearing 80 hats — and reporting it as "80
windows of evidence" would be dishonest. We do **not** do this. There is **one continuous BTC
path**, and credibility is sourced elsewhere:

1. **Out-of-sample by construction (the anchor).** The rule was fit on *equities* (SMA 200,
   ATR ×2.5, 8%/60-day stop). We apply it to BTC **with zero re-tuning**. BTC is therefore a
   genuine out-of-sample test of parameters fit on a different asset class — there is nothing
   fit to BTC, so there is nothing to overfit.
2. **Pre-registration.** Parameters (inherited, unchanged), benchmark (buy-&-hold BTC), and the
   pass/fail thresholds (§5) are fixed *in this spec, before any BTC backtest is run*. With ~3
   cycles, any post-hoc tweak is guaranteed curve-fit; pre-registration is the main honesty
   guard.
3. **Per-cycle disaggregation.** Every result is reported per bear cycle (2014–15, 2018,
   2021–22), never only aggregated. 3-of-3 consistent = weak-but-honest evidence; 2-of-3 is
   near coin-flip and will be labeled as such.
4. **Cross-asset replication.** The *same untuned rule* is run on ETH and 1–2 other long-history
   large caps as semi-independent corroboration (they are 0.7–0.8 correlated to BTC, so only
   partially independent — stated as a caveat).
5. **Robustness surface (plateau check, NOT optimization).** The metric is shown across a wide
   parameter grid to confirm the inherited params sit on a *smooth plateau*, not a lucky spike.
   Explicitly **not** used to pick a new BTC-best parameter set.
6. **Block bootstrap (weak supporting sanity check only).** Bootstrapping partly destroys the
   trend autocorrelation the strategy feeds on, so it can *understate* a real edge — reported
   with that caveat, never as the headline. Included only if time permits.

## 3. Data

- **Primary:** `BTC-USD` via `yfinance` (matches the repo data stack), daily, **2014-09 →
  present** (~11 years). Pre-2014 BTC data is exchange-fragmented and unreliable and is
  **excluded** (exclusion stated explicitly in the writeup) rather than spliced onto a shaky
  proxy.
- **Cycles (the N≈3):** 2014–15 bear, 2018 bear, 2021–22 bear, plus the current up-leg. Cycle
  date boundaries are defined in the script as explicit constants so the per-cycle table is
  reproducible.
- **Cross-asset replication set:** `ETH-USD` (~2017→), `LTC-USD`, and optionally `XRP-USD`
  — untuned replication only.

## 4. The rule — two configs, untuned, transferred from equities

Both configs reuse the existing `SMATrendFollowing` / trailing-stop machinery in
[strat_backtest.py](../../../backtest/strat_backtest.py) with parameters **inherited unchanged**
from the equity strategy. Spot BTC (1× — no leverage, no borrow drag).

- **Config 1 — Core trend signal.** BTC's own **SMA 200 + ATR ×2.5** band: bull-entry above
  `SMA200 + 2.5·ATR`, bear-exit below `SMA200 − 2.5·ATR`, hold in the band; next-day-open
  execution (`.shift(1)`), consistent with the equity engine.
- **Config 2 — Core + trailing stop.** Config 1 plus the **8% / 60-trading-day** trailing stop
  on BTC's own price (track running peak since entry; exit the day it closes 8% below peak; block
  re-entry for 60 trading days). BTC's fast 80% crashes make this the most relevant equity layer.
- **Deliberately excluded — dual-signal agreement.** BTC has no natural second index. ETH is too
  correlated and too short to serve as a confirming vote, so it is **not** forced into a dual
  role; it remains a separate cross-asset replication only.

Out-of-market → cash (no defensive rotation modeled in this study; keep it isolated).

## 5. Pre-registered pass/fail bar (fixed before running)

Verdict rule, committed here in advance:

- **PASS (transfers):** drawdown reduction vs buy-&-hold of **≥20pp in ≥2 of the 3 bear cycles**,
  **AND** CAGR give-up **≤30% of buy-&-hold's CAGR**, **AND** the inherited params sit on a
  smooth plateau (neighbors within ±20% of each param behave similarly — no knife-edge).
- **FAIL (does not transfer):** drawdown reduction fails in **≥2 of 3 cycles**, **OR** the return
  give-up leaves **Calmar worse than buy-&-hold**.
- **INCONCLUSIVE:** anything mixed — e.g. helped in 2-of-3 but only on a knife-edge parameter
  spike, or drawdown clearly helped while return was destroyed in a way the thresholds don't
  cleanly resolve. Reported honestly as "cannot be established with available data."

The verdict is reported for **each config** (core, core+stop) independently.

## 6. Benchmark & metrics

- **Benchmark:** buy-&-hold spot BTC over the same 2014→present path.
- **Single continuous path** — no rolling-window table (see §2). The **per-cycle drawdown table**
  is the disaggregation that substitutes for window count.
- **Metrics** (repo's existing vocabulary): CAGR, worst peak-to-trough drawdown, Calmar,
  single-path Sharpe, trade count, and **per-cycle max drawdown** (each of the 3 bears
  individually, strategy vs buy-&-hold).

## 7. Deliverables

- **`backtest/btc_trend_screen.py`** — single-path engine: fetches BTC-USD (+ cross-asset set),
  runs both configs vs buy-&-hold, prints the headline KPI table + per-cycle drawdown table,
  the param-plateau surface, and the cross-asset replication table. Reuses `strat_backtest.py`
  classes; no re-implementation of the signal.
- **`docs/strategies/btc-trend-following.md`** — writeup: the §2 credibility framing, the §5
  pre-registered bar (quoted verbatim, dated before results), the result tables, and the
  verdict per config.
- **README "Explored and set aside" entry** if the outcome is negative/inconclusive; a proper
  strategy-doc promotion only if it PASSES (that promotion is a later, separate cycle).

## 8. Testing

- Reuse the existing test harness conventions in `tests/`. Add targeted unit tests for anything
  new in the screen (cycle-boundary partitioning, per-cycle drawdown computation, buy-&-hold
  baseline). The inherited signal logic is already covered by existing tests and is not
  re-tested here.
- **Reconstruction sanity:** confirm the BTC buy-&-hold path reproduces known BTC drawdown
  magnitudes (e.g. 2021→2022 ≈ −75% to −77%) as a data-integrity check before trusting strategy
  numbers.

## 9. Risks & honest caveats (to state in the writeup)

- **N≈3 is small.** Even a clean 3-of-3 PASS is weak evidence; the writeup will not overclaim.
- **Cross-asset replication is only semi-independent** (0.7–0.8 correlation).
- **Regime concentration:** BTC's three bears are one repeated archetype; the rule succeeding
  says little about how it behaves in a *novel* crypto regime (e.g. a prolonged low-vol grind or
  a structural repricing) it has never seen.
- **yfinance data quality** for early BTC/alts; validate before trusting.
