# Covered-Call Income Optimizer — pending live run

> **No numbers yet.** This report was scheduled to be generated on 2026-09-16 but
> the sandbox's egress IP was rate-limited by Yahoo (HTTP 429), so no price
> history could be fetched. Per the project's honesty policy, numbers are **not**
> fabricated. All engine logic is offline-unit-tested on synthetic series
> (`tests/test_realized_iv.py`, `tests/test_cc_income.py`,
> `tests/test_cc_optimizer.py`); only the live data fetch is blocked.

## How to generate this report

Run on an unthrottled runner (e.g. the same GitHub Actions runner as
`daily_check.yaml`), with a working yfinance egress:

```bash
pip install -r requirements.txt
python -m options.cc_optimizer --tickers NVDA,PLTR,TQQQ --start 2020-01-01 \
    --out docs/covered-call-income-2026-09-16.md
```

That command sweeps the 60-config grid (Δ × DTE × IVR-gate × earnings-rule) per
ticker, ranks by annualized premium yield subject to **keep rate ≥ 80%** and
**total-return drag ≤ 3 pp/yr**, and overwrites this file with the per-ticker
ranked frontier plus a **recommended config per ticker** and the standing
modeling caveats.

See [`strategies/covered-call-income.md`](strategies/covered-call-income.md) for
the strategy write-up and the contrast with the negative overlay finding.
