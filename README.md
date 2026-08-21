# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. It layers a **200-Day SMA + ATR trend signal**, **dual-signal agreement** (the NASDAQ-100 and S&P 500 must concur), and a **trailing stop** for crash protection into a single daily recommendation — aiming to compound through bull markets while exiting defensively before systemic drawdowns. See [How It Works](#how-it-works) for the mechanics.

---

## TL;DR

**The strategy:** hold **3× TQQQ only when the NASDAQ-100 *and* S&P 500 both trend bullish** (200-day SMA + 2.5·ATR); otherwise rotate to defensive assets / cash. A **tax-advantaged** account adds an **8% / 60-day S&P trailing stop** for crash protection; a **taxable** account skips it (the stop's extra turnover is net-negative after tax). One daily recommendation, from `bot.py`.

**Performance** — 26-year rolling windows, next-day-open execution, era-accurate borrow rates + tax modeling ([methodology](docs/strategies/methodology.md)):

| Configuration | Avg annual return | Worst drawdown | Trades / 26y |
| :--- | ---: | ---: | ---: |
| Dual-signal **+ trailing stop** (tax-advantaged) | **24.6%** | **−65%** | ~18 |
| Dual-signal, no stop (taxable) | 25.8% | −85% | ~9 |
| Buy & Hold 3× (baseline) | 3.1% | −100% | 1 |

On a single continuous 1990–2026 path, the recommended (with-stop) config returns **≈29%/yr** at **≈−61% max drawdown**, with **Sharpe ≈ 0.67** and **Calmar ≈ 0.47** (Sharpe/Calmar are single-path figures — the rolling engine reports the return distribution + drawdown above, not Sharpe).

**In one line:** it turns a 3× ETF that Buy & Hold takes to ~−100% through the dot-com and 2008 bears into a survivable ~25%/yr compounder — at the cost of a still-deep ~−65% worst case, which is leverage's structural floor (dropping to 2× roughly halves it). Options overlays, an EMA signal, and volatility-targeted sizing were all tried and **did not improve on this** — see [Explored and set aside](#explored-and-set-aside-negative-results).

---

### How It Works

`bot.py` produces one daily recommendation by stacking three layers, each fixing a weakness of the layer before it. The Discord report shows the underlying signals for transparency, but the headline **recommended action** is the combined verdict of all three. Each layer has its own strategy doc with the full mechanics, backtests, and caveats:

*   **Layer 1 — Core trend signal ([SMA 200 + ATR buffer](docs/strategies/core-trend-signal.md)).** Classifies each index's trend against a 200-day SMA with a volatility buffer sized by Average True Range — bullish above `SMA200 + 2.5*ATR`, bearish below `SMA200 - 2.5*ATR`, hold in between. The ATR buffer widens in volatile markets and tightens in calm ones so the strategy doesn't react to every minor wiggle.
*   **Layer 2 — Noise filter ([dual-signal agreement](docs/strategies/dual-signal-agreement.md)).** Flips state only when **both** the NASDAQ-100 (^NDX) *and* the S&P 500 (^GSPC) independently agree; if they disagree, it holds the prior position. This filters single-signal head-fakes. It still trades ^NDX (TQQQ) exposure — the S&P is a second confirming vote, not a separate position.
*   **Layer 3 — Crash protection ([trailing stop](docs/strategies/trailing-stop.md)).** A faster safety net for sharp crashes the slow trend signal would miss: while in a position, track the running peak of the *unleveraged* S&P 500 since entry; the day it closes **8% below that peak**, exit immediately, then block re-entry for a **60-trading-day cooldown**.

```mermaid
flowchart LR
    Cash([In cash]) -->|both bullish| Pos([In position])
    Pos -->|S&P falls 8%| Cool([Cooldown 60d])
    Pos -->|trend bearish| Cash
    Cool -->|60 days elapse| Cash
```

The **recommended action** is "in the market" only when both indices agree bullish **and** the trailing stop has not fired. The daily report prints this action twice — once for a **tax-advantaged account** (with the trailing stop) and once for a **taxable account** (dual-signal only, *without* the stop), because the stop's extra turnover is a net-negative return trade after tax (see [Tax Treatment](docs/strategies/tax-treatment.md)).

### Explored and set aside (negative results)

Several ideas for improving the strategy were tested and **none beat the production
trend rule** — recorded here (and elaborated in the
[research retrospective](docs/research-retrospective-2026-08.md)) so they aren't
re-explored:

- **Options overlay** — a self-contained [`options/`](options/) package tested a
  covered call, a two-sided premium engine, a protective-put hedge, a collar, and a
  put-only structure on the 3× TQQQ sleeve. None beat the bare trend rule at any
  strike, on the single-signal *or* production allocation (Calmar: bare Trend
  0.35–0.47 vs every overlay ≤ 0.18; the collar is net-negative). Earlier "collar
  wins" drafts were a pricing artifact from two backtesting bugs (a 1-day sleeve
  lookahead and a strike-selection-vs-pricing vol mismatch), now fixed. Dropped as an
  execution candidate; kept as a documented negative finding. See
  [Options Overlay](docs/strategies/options-overlay.md).
- **EMA 50/200 signal** (vs SMA 200 in the dual-signal rule) — ~neutral in practice.
- **Volatility-targeted position sizing** — ~neutral (Sharpe unchanged across both
  the 1990–2026 and 2010+ eras); it is redundant with a trend rule that already
  rotates to cash in high-volatility (bear) regimes.

**Takeaway:** the trend strategy is near its practical optimum. The only lever that
meaningfully changes its deep (−50% to −65%) worst-case drawdowns is **leverage**
(2× roughly halves the worst case for a modest return give-up), not a smarter signal.

---

### Backtesting Methodology

All results are produced by rolling 26-year backtests stepped forward **monthly** from the earliest available data through 2000-07, exposing every strategy to the Dot-com crash, 2008 GFC, COVID crash, and 2022 rate-shock bear. The engine uses next-day-open execution, era-accurate historical borrow rates, and a money-market cash yield, and reports two drawdown metrics (peak-to-trough and vs-initial-capital). Full engine details and metric definitions: **[Methodology](docs/strategies/methodology.md)**.

Backtest parameters: **26-year** rolling windows · **$10,000** lump sum (no DCA) · pre-tax (except the [Tax Treatment](docs/strategies/tax-treatment.md) doc).

---

## Backtest Results — Final Decision

The bot's recommended configuration is **3x TQQQ, SMA 200 (ATR ×2.5) + dual-signal agreement**, differing only by account type. Headline rolling-backtest performance vs the Buy & Hold baseline:

| Configuration | Account | Avg TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: |
| Dual-signal agreement (no stop) | Taxable | **25.81%** | -84.95% | 9 |
| Dual-signal agreement + Trailing Stop 8%/60d | Tax-advantaged | 24.59% | **-64.78%** | 18 |
| Buy & Hold (baseline) | — | 3.10% | -99.98% | 1 |

*26-year rolling backtest, 172 windows, 3x ^NDX (TQQQ). The trailing stop trades ~1pp of average return for a ~20pp shallower worst-case drawdown; in a taxable account the stop is a net-negative return trade after tax, so it is dropped there.*

### Strategy docs (detail + full tables)

Each strategy/feature has its own doc with the mechanics, its full result tables, narrative, and caveats. Headline result per feature:

| Strategy / feature | Headline result | Doc |
| :--- | :--- | :--- |
| **Core trend signal** (SMA 200 + ATR) | SMA 200 (ATR ×2.5) beats Buy & Hold at every leverage tier with a shallower drawdown; ~23% Avg TWR at 3x vs 3.1% B&H. | [core-trend-signal](docs/strategies/core-trend-signal.md) |
| **Dual-signal agreement** | Best return + fewest trades of any signal rule: 25.81% Avg TWR, 9 trades — beats single-signal and T+2. | [dual-signal-agreement](docs/strategies/dual-signal-agreement.md) |
| **Trailing stop** (crash protection) | Largest drawdown reducer in every crash: e.g. dot-com -83% → -51%, COVID -70% → -43%; Worst DD -85% → -65%. | [trailing-stop](docs/strategies/trailing-stop.md) |
| **Velocity stop** (alternative) | Equal-or-better crash protection than the peak stop but a real 3-6× larger return cost and *more* trades — not adopted. | [velocity-stop](docs/strategies/velocity-stop.md) |
| **QQQ (1x)** | Unleveraged cross-check: dual-signal agreement again best at 14.69% Avg TWR / 9 trades; validates Table 1's 1x tier. | [qqq-1x](docs/strategies/qqq-1x.md) |
| **Tax treatment** | After tax, the stop's return edge inverts for the dual pair (23.61% no-stop vs 19.82% with stop) — hence no stop in taxable accounts. | [tax-treatment](docs/strategies/tax-treatment.md) |
| **Global equities** (MSCI World+EM → VT) | Strategy ranking holds on a global base — EMA 50/200 leads at every tier — at lower return levels than US tech (reconstruction cross-check). | [global-equities](docs/strategies/global-equities.md) |
| **Options overlay** (negative result) | No overlay (covered call / collar / protective put) beats the bare trend rule once two backtest bugs are fixed (Calmar: Trend 0.35–0.47 vs all overlays ≤ 0.18; collar net-negative). Dropped; kept as a documented negative finding. | [options-overlay](docs/strategies/options-overlay.md) |

---

### **Changelog**

See [CHANGELOG.md](CHANGELOG.md) for a full history of changes with dates.

---

### **Strategy Research & Theoretical Basis**
The bot implements a **trend-following strategy** for leveraged ETFs, grounded in a few quantitative-finance principles (the mechanics themselves are in [How It Works](#how-it-works)):

1. **Trend-filtering for leveraged ETFs:** Leveraged ETFs suffer from *volatility decay*. Research (e.g. Meb Faber) shows that 200-day trend filters effectively "clip the left tail" of risk, preventing catastrophic drawdowns during secular bear markets.
2. **Layered noise-and-crash filtering:** the ATR buffer, dual-signal agreement, and trailing stop each target a distinct failure mode — minor noise, single-signal head-fakes, and fast crashes respectively — rather than leaning on one filter to do everything.
3. **Core objective:** improve **risk-adjusted returns** by preserving capital during systemic failures rather than trying to time minor market tops.

---

### **System Architecture**
* **Automation:** Powered by **GitHub Actions**, which runs the script automatically after market close.
* **Data Engine:** Uses `yfinance` to fetch reliable, real-time market data.
* **Notification:** Integrated with **Discord Webhooks** for instant, actionable trading recommendations.

---

### **Getting Started**
1. **Clone/Fork** this repository.
2. **Configure Secrets:** Navigate to `Settings` > `Secrets and variables` > `Actions` and add your `DISCORD_WEBHOOK` URL.
3. **Dependencies:** Install the required libraries
4. **Automation:** The workflow file `.github/workflows/daily_check.yml` is pre-configured to run automatically every trading day.

### **Risk Disclaimer**
This project is for educational and monitoring purposes only. Leveraged ETFs (such as TQQQ) are highly volatile instruments. The 200 SMA strategy is designed to mitigate long-term systemic risk but may face "whipsaw" losses during sideways or consolidating markets. Please assess your risk tolerance before executing real-world trades based on these signals.
