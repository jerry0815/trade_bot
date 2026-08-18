# Backtesting Methodology

[← Back to README](../../README.md)

All strategy results in the strategy docs are produced by rolling 26-year backtests stepped forward **monthly** from the earliest available data through the latest valid start date (2000-07). This eliminates timing luck and exposes strategies to every major market regime — the Dot-com crash, 2008 Financial Crisis, COVID crash, and the 2022 rate-shock bear market.

**Key engine features:**
- **Next-day open execution** — orders execute at the following day's open, not the signal day's close
- **Accurate TWR annualisation** — computed from actual trading days, not configured period years
- **Historical borrow rates** — leverage drag uses era-accurate interest rates (4%–9% depending on decade)
- **Cash yield** — idle cash earns 80% of the prevailing borrow rate (money-market proxy)
- **Parallel computation** — all rolling windows run concurrently via `ThreadPoolExecutor`

**Two drawdown metrics** (both reported in the rolling tables):
- **Worst DD** — the deepest **peak-to-trough** decline (trough ÷ the strategy's own *running peak* − 1). Measures giving back accumulated *paper gains*.
- **Worst DD vs Init** — the deepest dip below the **initial $10,000** (lowest equity ÷ *starting capital* − 1; 0 means a window never went below the money put in). Measures losing your *own principal*. For a strategy that has compounded a lot, Worst DD can be far deeper than Worst DD vs Init — the difference is gains-given-back vs. principal-lost. The gap is near-zero for setups whose worst window starts right before a crash (no gains banked yet — pure sequence risk).

**Backtest Parameters:**
- Rolling period: **26 years** per window
- Initial investment: **$10,000 lump sum** (no DCA)
- Tax: **not applied** (pre-tax returns), except where a strategy doc explicitly states after-tax results (see [Tax Treatment](tax-treatment.md))

## The overlapping-window caveat

The rolling suites use monthly-stepped windows (typically 172–181 per table) that share nearly all their history with their neighbors, so the window count is much less independent evidence than the raw number suggests. Individual strategy docs restate this caveat where it matters most.
