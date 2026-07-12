# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. By utilizing a **200-Day Simple Moving Average (200 SMA)**, the system provides real-time trend assessment to maximize compound growth during bull markets and execute defensive exit strategies before systemic bear markets.

---

### Strategy Logic: Dynamic ATR Protection

The system provides a clear, rule-based approach to market exposure. We move beyond simple "price crossing SMA" signals by adding a dynamic volatility buffer using the **Average True Range (ATR)**.

**The Decision Rules:**

*   **Bullish:** When the price rises **above** the upper buffer:
    `Price > (SMA200 + 2.5 * ATR)`
    *Action: Enter or maintain long positions to capture growth.*

*   **Bearish:** When the price falls **below** the lower buffer:
    `Price < (SMA200 - 2.5 * ATR)`
    *Action: Exit to cash or short-term Treasuries (e.g., SGOV/BIL) to protect capital.*

*   **Neutral:** When the price is **inside** the buffer:
    `(SMA200 - 2.5 * ATR) <= Price <= (SMA200 + 2.5 * ATR)`
    *Action: Hold existing position. This prevents "whipsawing" during indecisive market periods.*

### Key Components

*   **The Trend Anchor (SMA 200):** We utilize the 200-day Simple Moving Average as our "North Star" to filter out market noise and focus on the primary long-term trend.
*   **The Volatility Shield (ATR):** By applying a 2.5x ATR multiplier, we create a "breathing room" buffer that expands during volatile markets and tightens during calm ones, ensuring the strategy adapts to current market conditions.
*   **Disciplined Execution:** By automating these calculations, the system removes emotional bias and ensures strict, math-based adherence to your risk parameters.

---

### Backtesting Methodology

All results below are produced by rolling 26-year backtests stepped forward **monthly** from the earliest available data through the latest valid start date (2000-06). This eliminates timing luck and exposes strategies to every major market regime — the Dot-com crash, 2008 Financial Crisis, COVID crash, and the 2022 rate-shock bear market.

**Key engine features:**
- **Next-day open execution** — orders execute at the following day's open, not the signal day's close
- **Accurate TWR annualisation** — computed from actual trading days, not configured period years
- **Historical borrow rates** — leverage drag uses era-accurate interest rates (4%–9% depending on decade)
- **Cash yield** — idle cash earns 80% of the prevailing borrow rate (money-market proxy)
- **Parallel computation** — all rolling windows run concurrently via `ThreadPoolExecutor`

**Backtest Parameters:**
- Rolling period: **26 years** per window
- Initial investment: **$10,000 lump sum** (no DCA)
- Tax: **not applied** (pre-tax returns)

---

### Table 1: NASDAQ-100 (^NDX) — Lump Sum Performance
*Date range: 1986-04-29 to 2000-06-28 (171 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 3.14% | 3.86% | -9.09% | -99.98% | 0 |
| **3x** | **SMA 200 (ATR x2.5)** | **23.57%** | **24.27%** | **10.53%** | **-81.38%** | **15** |
| **3x** | EMA 50/200 | 23.55% | 25.10% | 10.81% | -90.41% | 14 |
| **3x** | VIX < 25 | -1.82% | -1.06% | -10.36% | -99.85% | 124 |
| **3x** | RSI 30/70 | -5.69% | -5.79% | -12.73% | -99.85% | 22 |
| | | | | | | |
| **2x** | Buy & Hold | 11.21% | 11.86% | 1.54% | -98.95% | 0 |
| **2x** | **SMA 200 (ATR x2.5)** | **20.71%** | **21.03%** | **10.96%** | **-62.51%** | **15** |
| **2x** | EMA 50/200 | 21.07% | 21.74% | 11.57% | -73.90% | 14 |
| **2x** | VIX < 25 | 3.50% | 4.23% | -3.20% | -98.17% | 124 |
| **2x** | RSI 30/70 | 1.75% | 1.88% | -2.76% | -96.66% | 22 |
| | | | | | | |
| **1x** | Buy & Hold | 11.67% | 12.06% | 6.12% | -82.99% | 0 |
| **1x** | **SMA 200 (ATR x2.5)** | **13.95%** | **14.20%** | **8.48%** | **-35.77%** | **15** |
| **1x** | EMA 50/200 | 14.33% | 14.59% | 8.99% | -39.94% | 14 |
| **1x** | VIX < 25 | 5.54% | 6.03% | 1.55% | -83.44% | 124 |
| **1x** | RSI 30/70 | 4.87% | 4.86% | 3.28% | -74.40% | 22 |

> **Bold = best risk-adjusted result per leverage tier.** SMA 200 (ATR x2.5) dominates at 3x — highest average TWR with the lowest drawdown, making it the preferred strategy for leveraged exposure.

---

### Table 2: S&P 500 (^GSPC) — Lump Sum Performance
*Date range: 1985-07-31 to 2000-06-28 (180 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 2.75% | 3.37% | -2.54% | -98.86% | 0 |
| **3x** | **SMA 200 (ATR x2.5)** | **13.66%** | **13.90%** | **9.61%** | **-55.80%** | **12** |
| **3x** | EMA 50/200 | 11.61% | 11.92% | 6.73% | -79.40% | 12 |
| **3x** | VIX < 25 | 0.63% | 0.87% | -2.94% | -95.46% | 123 |
| **3x** | RSI 30/70 | 3.95% | 4.52% | 0.08% | -95.10% | 23 |
| | | | | | | |
| **2x** | Buy & Hold | 6.38% | 6.72% | 3.38% | -91.49% | 0 |
| **2x** | **SMA 200 (ATR x2.5)** | **11.39%** | **11.49%** | **9.09%** | **-40.49%** | **12** |
| **2x** | EMA 50/200 | 10.41% | 10.51% | 7.44% | -59.38% | 12 |
| **2x** | VIX < 25 | 2.65% | 2.87% | 0.06% | -83.34% | 123 |
| **2x** | RSI 30/70 | 6.01% | 6.04% | 4.06% | -81.45% | 23 |
| | | | | | | |
| **1x** | Buy & Hold | 7.00% | 7.09% | 5.33% | -56.90% | 0 |
| **1x** | **SMA 200 (ATR x2.5)** | **8.19%** | **8.25%** | **6.80%** | **-21.83%** | **12** |
| **1x** | EMA 50/200 | 7.89% | 8.09% | 6.02% | -33.26% | 12 |
| **1x** | VIX < 25 | 3.85% | 4.03% | 2.23% | -46.92% | 123 |
| **1x** | RSI 30/70 | 5.78% | 5.80% | 4.94% | -52.65% | 23 |

> **SMA 200 (ATR x2.5) wins across all leverage tiers on S&P 500** — dramatically lower drawdowns (-21.83% at 1x vs -56.90% Buy & Hold) while maintaining superior or comparable returns.

---

### Table 3: NASDAQ-100 Returns + S&P 500 Signal — Lump Sum Performance
*Trade ^NDX (TQQQ) exposure but use ^GSPC (S&P 500) trend to determine in/out.*
*Date range: 1986-04-29 to 2000-06-28 (171 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 3.14% | 3.86% | -9.09% | -99.98% | 0 |
| **3x** | **SMA 200 (ATR x2.5)** | **23.59%** | **23.97%** | **12.04%** | **-83.79%** | **12** |
| **3x** | EMA 50/200 | 22.97% | 23.53% | 9.02% | -88.61% | 12 |
| **3x** | VIX < 25 | -1.82% | -1.06% | -10.36% | -99.85% | 124 |
| **3x** | RSI 30/70 | 3.75% | 3.64% | -0.89% | -99.39% | 23 |
| | | | | | | |
| **2x** | Buy & Hold | 11.21% | 11.86% | 1.54% | -98.95% | 0 |
| **2x** | **SMA 200 (ATR x2.5)** | **20.37%** | **20.57%** | **11.62%** | **-64.66%** | **12** |
| **2x** | EMA 50/200 | 20.44% | 20.96% | 10.12% | -70.83% | 12 |
| **2x** | VIX < 25 | 3.50% | 4.23% | -3.20% | -98.17% | 124 |
| **2x** | RSI 30/70 | 8.18% | 8.03% | 5.52% | -92.72% | 23 |
| | | | | | | |
| **1x** | Buy & Hold | 11.67% | 12.06% | 6.12% | -82.99% | 0 |
| **1x** | **SMA 200 (ATR x2.5)** | **13.64%** | **13.94%** | **8.64%** | **-35.77%** | **12** |
| **1x** | EMA 50/200 | 13.91% | 14.49% | 8.17% | -40.11% | 12 |
| **1x** | VIX < 25 | 5.54% | 6.03% | 1.55% | -83.44% | 124 |
| **1x** | RSI 30/70 | 7.99% | 7.88% | 6.60% | -64.15% | 23 |

> **vs. Table 1 (NDX own signal):** SMA 200 produces nearly identical average TWR at every leverage tier
> while generating ~3 fewer round-trips per period. The worst-case floor improves slightly at 3x
> (12.04% vs 10.53%) but worst drawdown is marginally larger (-83.79% vs -81.38%) because ^GSPC
> exits a beat later when NDX crashes faster than the broader market.


---

### **Changelog**

See [CHANGELOG.md](CHANGELOG.md) for a full history of changes with dates.

---

### **Strategy Research & Theoretical Basis**
This bot implements a **Trend-Following Strategy** enhanced with a **Triple-Filter System** to mitigate "Whipsaw" (false signals). This methodology is supported by key quantitative finance principles:

1. **Trend-Filtering for Leveraged ETFs:** Leveraged ETFs are subject to *Volatility Decay*. Research (e.g., Meb Faber) suggests that 200-day trend filters effectively "clip the left tail" of risk, preventing catastrophic drawdowns during secular bear markets.
2. **The Triple-Filter Mechanism:**
    * **SMA 200:** Identifies the long-term regime (Bull vs. Bear).
    * **ATR (Average True Range) Filter:** Dynamically adjusts the "No-Trade Zone" based on current market volatility, preventing the bot from overreacting to minor noise in stable markets.
3. **Core Objective:** To improve **Risk-Adjusted Returns** by preserving capital during systemic failures rather than attempting to time minor market tops.

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
