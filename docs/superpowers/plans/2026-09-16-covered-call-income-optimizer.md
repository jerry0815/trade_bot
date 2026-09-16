# Covered-Call Income Optimizer — Implementation Plan

**Design:** [`../specs/2026-09-16-covered-call-income-optimizer-design.md`](../specs/2026-09-16-covered-call-income-optimizer-design.md)
**Branch:** `claude/inspiring-galileo-j1m1dc`

## Steps

1. **`options/greeks.py`** — add optional `put_skew_mult` / `call_skew_mult`
   kwargs to `get_strike_for_delta` (default to `PUT_SKEW_MULT` / `CALL_SKEW_MULT`
   module constants). Thread through `spread_strikes` if trivial. No behavior
   change when omitted.

2. **`options/realized_iv.py`** — pure `realized_vol(close, window=21,
   trading_days=252)` and `implied_proxy(realized, vrp_mult)`; fetch/cache wrapper
   `load_price_history(ticker, start, end, cache_dir="data")` using `_net.download`,
   persisting `data/<TICKER>_history.csv`.

3. **`options/cc_income.py`** — `CCConfig` dataclass + `CCResult` +
   `run_cc_income(price_df, iv_df, earnings_dates, cfg)`. Event-driven daily loop
   per the design (open/manage/settle, keep-shares intrinsic accounting,
   50%-profit & 21-DTE rolls). Income KPIs + standard KPIs (mirror
   `overlay_backtest._compute_kpis` conventions). Include `load_earnings_dates`
   helper with yfinance→synthetic-quarterly fallback.

4. **`options/cc_optimizer.py`** — `sweep(price_df, iv_df, earnings_dates,
   grid)`, `score_config(kpis, keep_rate_min=0.80, drag_cap=0.03)`, `main(argv)`
   CLI writing the per-ticker Markdown report with recommended configs + caveats.

5. **Tests** — `tests/test_realized_iv.py`, `tests/test_cc_income.py`,
   `tests/test_cc_optimizer.py`, extend `tests/test_greeks.py`. All offline on
   synthetic series. `python -m pytest tests/ -q` green.

6. **Docs** — `docs/strategies/covered-call-income.md`; new section in
   `options/README.md`; `CHANGELOG.md` entry.

7. **Live report (best-effort)** — attempt
   `python -m options.cc_optimizer --tickers NVDA,PLTR,TQQQ --start 2020-01-01
   --out docs/covered-call-income-2026-09-16.md`. If yfinance is throttled,
   commit the engine + tests + docs and note the exact command to run on an
   unthrottled runner; do **not** fabricate numbers.

## Validation

- `python -m pytest tests/ -q` passes.
- No regression in existing option tests (greeks change is backward compatible).
- Collateral invariant asserted in the sim (never > `shares // 100`).
- NAV reconciliation asserted daily in tests.
