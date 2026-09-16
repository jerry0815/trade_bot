# Covered-Call Income Optimizer

[← Back to README](../../README.md) · Related: [Options Overlay (negative result)](options-overlay.md) · [Methodology](methodology.md)

A focused engine for a **different question** than the [options overlay
study](options-overlay.md). That study asked whether an options structure
improves the **total return** of a leveraged (3× TQQQ) *trend sleeve* and found a
robust **negative** result — covered calls were the worst overlay because they
short exactly the fat-right-tail convexity a trend-follower needs.

Here the premise is inverted: the holder owns NVDA / PLTR / TQQQ as a **long-term
position they intend to keep**, and wants **cash flow** from writing calls
against those shares while **minimizing call-away**. Total-return maximization is
*not* the objective; income per unit of upside given up is. Because the shares
are held regardless, a fresh engine ([`options/cc_income.py`](../../options/cc_income.py))
is warranted rather than bolting onto the regime-specific `overlay_backtest.py`.

## Objective function

Maximize **annualized premium yield** subject to keeping the shares:

- **Annualized premium yield** — `premium_collected / avg_position_value / years`.
- **Keep rate** — `1 − assigned_cycles / total_cycles`, the fraction of cycles
  whose short call was *not* ITM at close (i.e. did not cap the shares). Because
  the 21-DTE roll always pre-empts a literal expiry when `dte ≥ min_dte_exit`,
  "assigned" is measured as **ITM at close** — the cycle where the shares *would*
  have been called away.
- **Total-return drag** — `buyhold_CAGR − strategy_CAGR`, the upside sacrificed.

The optimizer favors high premium yield, **keep rate ≥ 80%**, and **drag ≤ 3
pp/yr**, tie-broken by lowest drag. Because "keep shares" is the stated priority,
the grid biases toward **low delta / far OTM**.

## IV model — realized-vol proxy

No live option chains are assumed. For each ticker
([`options/realized_iv.py`](../../options/realized_iv.py)):

1. `realized_vol(close, window=21)` — annualized std of daily log returns.
2. `implied_proxy(realized, vrp_mult)` — implied ≈ realized × `vrp_mult`
   (single-name IV runs ~1.1–1.3× trailing realized; NVDA 1.15, PLTR 1.20, TQQQ
   1.10).
3. The IV-Rank gate reuses [`iv_loader.compute_iv_rank`](../../options/iv_loader.py)
   on the proxy IV series.

This is uniform across names, needs only price history (cached to
`data/<TICKER>_history.csv`), and deliberately differs from the VXN-based TQQQ
proxy so the methodology is self-contained per name.

## Simulator semantics

Event-driven daily loop ([`cc_income.py`](../../options/cc_income.py)):

- **Open** when flat, `IV_Rank ≥ ivr_gate`, and (if `earnings_rule="skip"`) no
  earnings date falls on/before the prospective expiry: sell
  `covered_call_contracts(shares)` calls, strike from
  `GreeksEngine.get_strike_for_delta(..., call_skew_mult=…)`.
- **Manage**: buy-to-close at 50% of max profit; else close at the mark once
  `DTE ≤ 21` (the roll); else settle at intrinsic on expiry.
- **Cash-settled at intrinsic; shares always retained** — same convention as the
  overlay engine.
- **NAV = `shares × price + cash`**, cash accruing `cash_yield`. The buy & hold
  baseline holds the identical shares + starting cash with no options.

## Collateral invariant

`covered_call_contracts(shares) ≤ shares // 100` (zero naked calls,
[`position_sizer.py`](../../options/position_sizer.py)) is **asserted in the
simulator** on every open and covered by a test.

## Running

```bash
pip install -r requirements.txt

python -m options.cc_optimizer --tickers NVDA,PLTR,TQQQ --start 2020-01-01 \
    --out docs/covered-call-income-2026-09-16.md

python -m pytest tests/ -q     # all logic is offline-unit-tested on synthetic series
```

The generated report ([`../covered-call-income-2026-09-16.md`](../covered-call-income-2026-09-16.md),
when produced on an unthrottled runner) carries the per-ticker ranked frontier
and a **recommended config per ticker**.

## Caveats — backtest-grade ranking signal, not tradeable P&L

- **Implied vol is a realized-vol proxy**, not a live chain — an approximation.
- Options are cash-settled at intrinsic; assignment, bid/ask, commissions, early
  exercise, borrow, and the tax drag of short-term premium are **not** modeled.
- Skew is a fixed multiplicative call offset, not a fitted surface.
- Earnings dates use yfinance when reachable, else a synthetic ~quarterly
  cadence for the `skip` rule.
- Treat the output as a **strategy-comparison / config-ranking signal**, not a
  P&L forecast — the same honesty class as the overlay docs.

## Further reading

- [`options/cc_income.py`](../../options/cc_income.py) — the simulator.
- [`options/cc_optimizer.py`](../../options/cc_optimizer.py) — the grid sweep + report.
- [`docs/strategies/options-overlay.md`](options-overlay.md) — the contrasting
  negative total-return result.
