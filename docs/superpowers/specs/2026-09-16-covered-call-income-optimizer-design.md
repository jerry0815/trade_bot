# Covered-Call Income Optimizer — Design

**Date:** 2026-09-16
**Status:** approved for implementation
**Branch:** `claude/inspiring-galileo-j1m1dc`

## Motivation

The holder wants **cash flow** from covered calls written against shares they
already own (NVDA, PLTR, TQQQ), while **keeping the shares** (minimizing
call-away / assignment). This is a *different objective* from the existing
[`options/`](../../../options/) overlay study, which asked whether options
improve **total return** on a *leveraged trend sleeve* and found a negative
result (covered calls were the worst overlay because they short the fat-right
tail the trend system needs).

Here the shares are held regardless, and the objective is income per unit of
upside given up — so a fresh, focused engine is warranted rather than bolting
onto the regime-specific `overlay_backtest.py`.

## Objective function (max income, keep shares)

Optimize for high premium income subject to retaining the shares:

- **Annualized premium yield** — `premium_collected / avg_position_value / years`.
- **Keep rate** — `1 - assigned_cycles / total_cycles` (fraction of cycles whose
  short call did *not* finish ITM at expiry; proxy for shares retained uncapped).
- **Total-return drag** — `buyhold_CAGR - strategy_CAGR` (upside sacrificed).

The optimizer favors high premium yield, keep rate ≥ a threshold (default 0.80),
and low drag. Bias toward **low delta / far OTM** because "keep shares" is the
stated priority.

## Data / IV model (decision: realized-vol proxy)

No live option chains are assumed. For each ticker:

1. `realized_vol(close, window=21)` — annualized std of daily log returns
   (`* sqrt(252)`).
2. `implied_proxy(realized, vrp_mult)` — implied ≈ realized × `vrp_mult`
   (single-name IV typically runs ~1.1–1.3× trailing realized; default 1.15).
   Per-ticker overrides: NVDA 1.15, PLTR 1.20 (richer), TQQQ 1.10.
3. IV-Rank gate reuses `iv_loader.compute_iv_rank` on the proxy IV series.

This is uniform across all three names and needs only price history (fetched via
`options/_net.download`, cached to `data/<TICKER>_history.csv` like the existing
NDX/GSPC/VIX CSVs). It is **backtest-grade for ranking configs, not tradeable
P&L** — same caveat class as the existing overlay docs. It deliberately differs
from the VXN-based TQQQ proxy so the methodology is self-contained per name.

## Modules

| File | Role |
|---|---|
| `options/realized_iv.py` | Pure: `realized_vol`, `implied_proxy`. Fetch/cache wrapper `load_price_history`. |
| `options/cc_income.py` | `CCConfig` + `run_cc_income(price_df, iv_df, earnings_dates, cfg) -> CCResult`. Event-driven daily covered-call sim. |
| `options/cc_optimizer.py` | `sweep(...)` grid + `score_config(...)` + CLI writing a per-ticker Markdown report. |
| `options/greeks.py` | Add optional `put_skew_mult` / `call_skew_mult` params to `get_strike_for_delta` (default = module constants; backward compatible). |

Reuse unchanged: `iv_loader.compute_iv_rank`, `position_sizer.covered_call_contracts`,
`_net.download`, and the KPI conventions in `overlay_backtest._compute_kpis`
(TRADING_DAYS=252, Rf=4.5%, Sharpe/MaxDD/CAGR/Calmar).

## Simulator semantics (`cc_income.py`)

`CCConfig` fields: `ticker`, `shares` (default derived from `initial_capital`),
`delta` (target |Δ|), `dte`, `ivr_gate`, `earnings_rule` (`"ignore"|"skip"`),
`profit_target=0.50`, `min_dte_exit=21`, `vrp_mult`, `call_skew_mult`,
`risk_free=0.045`, `cash_yield=0.045`, `initial_capital=100_000`.

Daily event loop over the price series:

- **Open**: when flat, IVR ≥ `ivr_gate`, and (if `skip`) no earnings date falls on
  or before the prospective expiry → sell `covered_call_contracts(shares)` calls.
  Strike via `GreeksEngine.get_strike_for_delta(S, dte/365, r, base_sigma, delta,
  "call", call_skew_mult=...)`. Record premium as a cash credit.
- **Manage** (short open): buy-to-close if unrealized profit ≥ `profit_target ×
  premium`; else close at mark if `DTE ≤ min_dte_exit`; else settle at intrinsic
  `max(S-K,0)×100×contracts` on expiry (cash-settled → shares retained; intrinsic
  paid models forgone upside = the "keep shares while defending" accounting, same
  convention as `overlay_backtest`).
- On close, realize option P&L into the book; on expiry ITM, increment
  `assigned_cycles`.
- **NAV** = `shares × price + cash`, where `cash` accrues `cash_yield` daily and
  reflects premium in / buybacks + intrinsic out. **Buy & hold baseline** =
  `shares × price + initial_cash`, no options, identical start.

`CCResult`: equity curve (Series), closed-trade list, `premium_collected`,
`option_pnl`, `assigned_cycles`, `cycles`, and a KPI dict extended with the
income metrics above plus standard CAGR/MaxDD/Sharpe/Calmar/win-rate/trade-count.

### Earnings dates

Helper `load_earnings_dates(ticker)`: try yfinance `Ticker.get_earnings_dates`;
on empty/failure fall back to a synthesized quarterly cadence (every ~91 days
from a per-ticker anchor). Documented as an approximation. `earnings_rule="skip"`
means: never hold a short call across an earnings date (don't open if an earnings
date precedes expiry; close before it if already open).

## Optimizer (`cc_optimizer.py`)

Grid: `delta ∈ {0.10,0.15,0.20,0.25,0.30}`, `dte ∈ {30,45}`,
`ivr_gate ∈ {0,30,50}`, `earnings_rule ∈ {"ignore","skip"}` → 60 configs/ticker.

`score_config(kpis)`: rank by annualized premium yield, filtered to
`keep_rate ≥ 0.80` and `drag ≤ drag_cap` (default 3%/yr); tie-break by lowest
drag. Also emit the raw ranked table so the holder sees the trade-off frontier.

CLI: `python -m options.cc_optimizer --tickers NVDA,PLTR,TQQQ --start 2020-01-01
--out docs/covered-call-income-2026-09-16.md`. Writes per-ticker ranked tables,
a **recommended config per ticker**, and the standing modeling caveats.

## Tests (offline, synthetic — no network)

- `tests/test_realized_iv.py` — `realized_vol` on a known constant-vol series;
  `implied_proxy` scaling; iv-rank integration shape.
- `tests/test_cc_income.py` — flat series ⇒ far-OTM call expires worthless, keep
  rate ~100%, positive income; strong uptrend ⇒ assignments occur, drag > 0;
  collateral never exceeds `shares // 100`; NAV reconciles to
  `shares×price + cash` each day.
- `tests/test_cc_optimizer.py` — grid runs on synthetic data; higher `ivr_gate`
  ⇒ fewer trades; recommended-config selection is deterministic.
- `tests/test_greeks.py` — new skew-override params respected (call at
  `call_skew_mult=1.0` differs from default 0.95).

## Docs

- `docs/strategies/covered-call-income.md` — strategy write-up; explicitly
  contrasts objective with the negative overlay finding; links recommended
  configs. Follows the existing `docs/strategies/*.md` back-link header style.
- Update `options/README.md` with a new "Covered-Call Income Optimizer" section
  clearly separated from the negative overlay finding.
- `CHANGELOG.md` entry.

## Network caveat

The sandbox proxy is frequently rate-limited (HTTP 429) for yfinance. All *logic*
is offline-unit-tested on synthetic data. The live benchmark report is generated
on an unthrottled runner; if the fetch fails in-session, document the exact run
command in the report rather than fabricating numbers.

## Non-goals

- No live order routing / broker integration.
- No fitted vol surface (skew stays a multiplicative offset).
- No modeling of bid/ask, commissions, early assignment, or borrow.
