# Dynamic Two-Sided Options Overlay

A regime-adaptive, Greek-governed options engine layered on top of the existing
200-day SMA + ATR trend system. It decides — every daily close — both the equity
allocation (100% TQQQ / 50-50 / 100% SGOV) **and** which option structure, if
any, to overlay, using a two-tier state machine of **price trend × volatility
regime**.

> **Design note — no Backtrader.** This overlay is a self-contained extension of
> the repo's own vectorized trend engine (`backtest/strat_backtest.py`), not a
> parallel Backtrader system. It reuses the same indicator conventions and adds
> an *event-driven* daily loop only where option state (DTE, per-leg
> mark-to-market, collateral) genuinely requires one.

## The execution matrix

| Regime | Condition | Holdings | IV / RSI gate | Structure |
|---|---|---|---|---|
| **Bull Expansion** | `Close > SMA200 + 1.5·ATR` | 100% TQQQ | `IVR < 30` | Buy 45-DTE put debit spread (long 30Δ / short 15Δ) — cheap tail hedge |
| | | | `IVR ≥ 40` | Sell 35-DTE covered call (15Δ, fully share-covered) |
| | | | `30 ≤ IVR < 40` | Idle |
| **Transition Band** | `within SMA200 ± 1.5·ATR` | 50% TQQQ / 50% SGOV | `IVR ≥ 60` | Sell 30-DTE bull put spread (short 30Δ / long 15Δ) |
| | | | `IVR < 60` | Idle |
| **Bear Defense** | `Close < SMA200 − 1.5·ATR` | 100% SGOV | `IVR ≥ 75 & RSI < 30` | Sell 30-DTE cash-secured put (10Δ, SGOV-collateralized) |
| | | | otherwise | Idle |

## Greek & risk guardrails

* **Delta** — shorts strictly OTM: covered calls target ~0.15Δ (never caps a 3x
  run), CSPs target ~0.10Δ.
* **Gamma (21-DTE rule)** — any short not already at its 50% profit target is
  force-closed at ≤ 21 DTE (`min_dte_exit`).
* **Vega** — the 50%-of-max-profit take is checked every day a short is open.
* **Collateral** (`position_sizer.py`) — `short_calls ≤ shares // 100` (zero
  naked calls) and `short_put_notional ≤ cash + SGOV` (100% cash-secured).
* **Emergency linkage** — a bear signal buys-to-close all covered calls *before*
  the equity sleeve is liquidated (`_should_close` returns `BEAR_CC_LIQUIDATION`).

## Entry filters (opt-in, `use_entry_filters=True`)

Extra confirmation gates applied **before opening a premium-selling structure**
(covered call, cash-secured put, bull-put spread, static CC). Premium sellers are
short gamma — a strong, fast trend runs through the short strike and turns theta
income into a loss — so these gates skip the open when the tape says "don't sell
premium here". Protective structures (`hedge_only`, `collar`, and the bull put
*debit* hedge) are never filtered.

| Gate | Rule | Config | Rationale |
|---|---|---|---|
| ADX | skip premium sells when `ADX ≥ premium_adx_max` | `premium_adx_max=40` | strong trend runs over short strikes |
| RSI floor | skip premium sells when `RSI ≤ premium_rsi_min` | `premium_rsi_min=20` | don't sell into a falling knife |
| RSI ceiling | skip **covered calls** when `RSI ≥ cc_rsi_max` | `cc_rsi_max=80` | a blow-off run caps exactly the upside we want |

Unknown (NaN) indicator values never block, so the ADX gate no-ops unless the data
carries an `ADX` column (`run_benchmark`/`live_monitor` add a Wilder-14 `ADX`; a
scale-invariant, always-present `RSI` drives the RSI gates). Blocked opens are
reported as the `Entry-Filter Blocks` KPI.

**Default OFF** so existing benchmark numbers are unchanged — turn on per model with
`run_model(data, "dynamic", use_entry_filters=True)`, for the whole suite with
`--entry-filters`, or measure the effect directly with `--compare-filters` (a
filters OFF-vs-ON table for the dynamic model). Whether the filters *help* is an
empirical question that must be answered on the real 2018–2026 run — on a synthetic
random path they slightly reduce activity without a regime edge to exploit.

## Modules

| File | Role |
|---|---|
| `iv_loader.py` | ^VXN ingestion → rolling 252-day IV-Rank (`compute_iv_rank` is pure/offline-testable). |
| `greeks.py` | Black-Scholes pricing + skew-adjusted delta→strike solver (+20% put / −5% call skew). |
| `regime.py` | The two-tier state machine (`classify_regime`, `RegimeParams`). |
| `position_sizer.py` | Contract sizing + collateral validation. |
| `overlay_backtest.py` | Event-driven simulator; runs the four benchmark models. |
| `run_benchmark.py` | CLI: assemble real data and print/save the 4-model KPI table. |
| `live_monitor.py` | Daily scanner: today's regime + target strikes; Discord webhook. |
| `_net.py` | Proxy-aware, retrying yfinance download helper. |

## The four benchmark models

1. **Buy & Hold** — 100% TQQQ.
2. **Trend** — 3-state SMA+ATR allocation, no options. (A refinement of the
   production *binary* bot — it adds the 50/50 transition sleeve — so its
   standalone return differs from the README's binary numbers.)
3. **Static CC** — Model 2 + mechanical 30-DTE ~20Δ covered calls in the bull
   regime, ignoring IV-Rank.
4. **Dynamic** — Model 2 + the full two-sided matrix above.

Plus a research model (`model="hedge_only"`, not in the default table): Model 2 +
a long put-debit spread held as **insurance** in the bull/transition regimes
(rolled near expiry, profit-taken on a crash, never sold into a vol spike). It
tests whether *buying* protection can beat plain Trend — see the finding below.

Reported KPIs: ending value, CAGR, max drawdown + duration, Sharpe (Rf=4.5%),
Sortino, Calmar, total premium collected, total debit paid, total option P&L,
option win-rate, and option trade count.

### Finding (real data, 2018–2026, pricing vol = VXN × 2.5)

The result **flips entirely on the pricing-vol assumption** (see Accounting).
Priced at TQQQ's realistic vol, at the empirically-central 2.5× VXN:

- **Covered calls (Model 3) beat Trend** — Calmar 3.4 vs 2.8, Sharpe 1.75 vs
  1.59, max drawdown −27% vs −33%, at essentially unchanged CAGR. The win is
  drawdown reduction (robust at 2.0–3.0× vol), not net option profit; capping the
  top smooths the curve while rich premium keeps return roughly flat.
- **Buying protection (`hedge_only`) does *not* beat Trend** — it trims crash
  drawdowns slightly but bleeds enough premium to net a lower Calmar (~2.7). Its
  apparent "win" only exists when options are mispriced at raw 1× VXN.
- **The two-sided Dynamic engine is worse than Model 3** — its short-*put*
  structures add left-tail risk (drawdown −44%). Sell the top; don't add to the
  bottom.

## Accounting assumptions

* NAV = `sleeve_value + unrealized_option_pnl`. Opening a position is
  NAV-neutral; short decay and assignment risk both show up as P&L.
* TQQQ's **actual** (already-3x) daily returns drive the equity sleeve; the SGOV
  sleeve earns a flat `cash_yield` (default 4.5%).
* Options are **cash-settled at intrinsic on expiry** — captures capped upside
  (covered calls) and tail losses (short puts) without modelling share
  assignment.
* Realized option P&L is **settled into the compounding book** on close, so a
  covered-call loss reduces the capital that keeps compounding — exactly as in a
  real account. This keeps returns and drawdowns self-consistent even when
  cumulative option P&L is large relative to the book.
* **Pricing vol = ^VXN × `pricing_iv_mult` (default 2.5).** ^VXN is the *1×*
  Nasdaq-100 vol index; these options are on *3×* TQQQ, whose realized vol ran
  ~2.5× VXN over 2018–2026 (median 2.51×, mean 2.58×). Pricing off raw VXN
  underprices every option ~2.5× and **inverts the strategy ranking** — buying
  options looks like free money and selling looks terrible. The default sets
  implied ≈ realized (no vol-risk premium gifted to either side). IV-Rank
  (regime gating) is a scale-invariant percentile and stays on raw VXN. Every
  option result is highly sensitive to this multiplier.
* The vertical skew is an empirical multiplicative offset, not a fitted surface.

These are backtest-grade approximations. Fills, bid/ask, early assignment, and
borrow are **not** modelled; treat results as strategy-comparison signal, not
tradeable P&L.

## Running

```bash
pip install -r requirements.txt

# 4-model benchmark (needs working yfinance egress; save a Markdown report):
python -m options.run_benchmark --start 2018-01-01 --end 2026-08-17 \
    --out docs/options-overlay-benchmark.md

# measure the RSI/ADX entry filters (dynamic model, filters OFF vs ON):
python -m options.run_benchmark --start 2018-01-01 --end 2026-08-17 --compare-filters
# ...or run the whole 4-model suite with filters enabled:
python -m options.run_benchmark --entry-filters

# refresh the IV-Rank history CSV:
python -m options.iv_loader

# today's regime + target option structure (posts to DISCORD_WEBHOOK if set):
python -m options.live_monitor

# unit tests:
python -m pytest tests/ -q
```

> **Sandbox note:** some CI/agent sandboxes route yfinance through a proxy whose
> egress IP Yahoo rate-limits (HTTP 429). `_net.py` handles the proxy's TLS
> correctly and retries, but a throttled IP still can't fetch. Run the benchmark
> on an unthrottled runner (e.g. the same GitHub Actions runner as
> `daily_check.yaml`).
