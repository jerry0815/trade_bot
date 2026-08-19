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

## Modules

| File | Role |
|---|---|
| `iv_loader.py` | ^VXN ingestion → rolling 252-day IV-Rank (`compute_iv_rank` is pure/offline-testable). |
| `greeks.py` | Black-Scholes pricing + skew-adjusted delta→strike solver (+20% put / −5% call skew). |
| `regime.py` | The two-tier state machine (`classify_regime`, `RegimeParams`). |
| `position_sizer.py` | Contract sizing + collateral validation. |
| `overlay_backtest.py` | Event-driven simulator; runs the four benchmark models. |
| `run_benchmark.py` | CLI: assemble real data and print/save the 4-model KPI table. |
| `rolling_benchmark.py` | 26-year rolling-window harness (Avg/Med/Worst CAGR + Worst DD). |
| `reconstruct_tqqq.py` | Synthetic pre-2010 TQQQ from ^NDX (validated ~0.999 vs real). |
| `production_sleeve.py` | Bridge: production dual-signal + stop allocation as a weight series. |
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

### Finding — negative result (not adopted)

Full write-up: [`docs/strategies/options-overlay.md`](../docs/strategies/options-overlay.md).
**No options overlay beats the bare trend rule.** Over 1990–2026, on the
single-signal sleeve *and* the production dual-signal + trailing-stop allocation, at
every strike, the Calmar of bare Trend (0.35 / 0.47) exceeds every overlay
(covered calls 0.16–0.18; put-only 0.06–0.14; collar net-negative, ~−0.02). The
overlays' drawdowns are *deeper* than doing nothing — a fairly-priced protective put
bleeds premium faster than its crash payoffs recover.

Earlier drafts claimed a collar "won." That was an artifact of two backtesting bugs,
now fixed: (1) a **1-day sleeve lookahead** (sized today's return with today's close)
that inflated trend-based CAGR ~4×, and (2) a **strike-selection-vs-pricing vol
mismatch** — strikes were chosen at the base vol but priced/marked at the skewed vol,
handing bought puts value their delta never paid for (the tell: raising the put skew
*improved* a put-buying strategy). Each option strike is now selected at the same
skew-adjusted vol it is priced at.

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

# 26-year rolling comparison (reconstructed TQQQ to 1990):
python -m options.rolling_benchmark

# unit tests:
python -m pytest tests/ -q
```

> **Not for execution.** This package is a **documented negative finding** (see the
> [strategy doc](../docs/strategies/options-overlay.md) and the
> [research retrospective](../docs/research-retrospective-2026-08.md)): no overlay
> beat the bare trend rule once two backtesting bugs were fixed. The live collar
> monitor and its scheduled workflow were removed; what remains is the research
> engine for reproducing the result.

> **Sandbox note:** some CI/agent sandboxes route yfinance through a proxy whose
> egress IP Yahoo rate-limits (HTTP 429). `_net.py` handles the proxy's TLS
> correctly and retries, but a throttled IP still can't fetch. Run the benchmark
> on an unthrottled runner (e.g. the same GitHub Actions runner as
> `daily_check.yaml`).
