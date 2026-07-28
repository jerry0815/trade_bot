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

**T+2 Confirmation:** A crossing of the upper or lower buffer doesn't execute immediately. The new signal (bullish or bearish) must persist for **2 consecutive trading days** before the bot changes state. A single day spent outside the buffer that reverts back inside the next day is treated as noise and ignored. This adds a short delay to every entry/exit but filters out one-day spikes that would otherwise trigger a whipsaw trade.

### Key Components

*   **The Trend Anchor (SMA 200):** We utilize the 200-day Simple Moving Average as our "North Star" to filter out market noise and focus on the primary long-term trend.
*   **The Volatility Shield (ATR):** By applying a 2.5x ATR multiplier, we create a "breathing room" buffer that expands during volatile markets and tightens during calm ones, ensuring the strategy adapts to current market conditions.
*   **T+2 Signal Confirmation:** Buy/sell signals must hold for two consecutive trading days before a state change executes, filtering out single-day false signals.
*   **Disciplined Execution:** By automating these calculations, the system removes emotional bias and ensures strict, math-based adherence to your risk parameters.

---

### Backtesting Methodology

All results below are produced by rolling 26-year backtests stepped forward **monthly** from the earliest available data through the latest valid start date (2000-07). This eliminates timing luck and exposes strategies to every major market regime — the Dot-com crash, 2008 Financial Crisis, COVID crash, and the 2022 rate-shock bear market.

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
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 3.10% | 3.84% | -9.09% | -99.98% | 1 |
| **3x** | **SMA 200 (ATR x2.5, T+2)** | **23.33%** | **24.25%** | **11.21%** | **-84.99%** | **13** |
| **3x** | EMA 50/200 | 23.52% | 25.05% | 10.81% | -90.41% | 13 |
| **3x** | VIX < 25 | -1.84% | -1.10% | -10.36% | -99.85% | 124 |
| **3x** | RSI 30/70 | -5.70% | -5.81% | -12.73% | -99.85% | 22 |
| | | | | | | |
| **2x** | Buy & Hold | 11.17% | 11.83% | 1.54% | -98.95% | 1 |
| **2x** | **SMA 200 (ATR x2.5, T+2)** | **20.57%** | **21.16%** | **11.42%** | **-66.80%** | **13** |
| **2x** | EMA 50/200 | 21.04% | 21.72% | 11.57% | -73.90% | 13 |
| **2x** | VIX < 25 | 3.48% | 4.20% | -3.20% | -98.17% | 124 |
| **2x** | RSI 30/70 | 1.75% | 1.81% | -2.76% | -96.66% | 22 |
| | | | | | | |
| **1x** | Buy & Hold | 11.65% | 12.06% | 6.12% | -82.99% | 1 |
| **1x** | **SMA 200 (ATR x2.5, T+2)** | **13.89%** | **14.10%** | **8.70%** | **-35.77%** | **13** |
| **1x** | EMA 50/200 | 14.31% | 14.56% | 8.99% | -39.94% | 13 |
| **1x** | VIX < 25 | 5.52% | 6.03% | 1.55% | -83.44% | 124 |
| **1x** | RSI 30/70 | 4.86% | 4.86% | 3.28% | -74.40% | 22 |

> **Bold = best risk-adjusted result per leverage tier.** With T+2 confirmation, SMA 200 (ATR x2.5) runs essentially neck-and-neck with EMA 50/200 on average TWR at every tier (within ~0.5pp) and consistently posts a shallower max drawdown (-84.99% vs -90.41% at 3x, -66.80% vs -73.90% at 2x, -35.77% vs -39.94% at 1x). The worst-case floor, though, is mixed: SMA has the better floor at 3x (11.21% vs EMA's 10.81%), but EMA has a modestly higher floor at 2x (11.57% vs 11.42%) and 1x (8.99% vs 8.70%). The consistently lower drawdown across all three tiers is what keeps SMA the preferred strategy for leveraged exposure.

---

### Table 2: S&P 500 (^GSPC) — Lump Sum Performance
*Date range: 1985-07-31 to 2000-07-28 (181 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 2.75% | 3.34% | -2.54% | -98.86% | 1 |
| **3x** | SMA 200 (ATR x2.5, T+2) | 10.97% | 11.33% | 5.50% | -82.28% | 11 |
| **3x** | **EMA 50/200** | **11.60%** | **11.88%** | **6.73%** | **-79.40%** | **12** |
| **3x** | VIX < 25 | 0.64% | 0.88% | -2.94% | -95.46% | 123 |
| **3x** | RSI 30/70 | 3.95% | 4.52% | 0.08% | -95.10% | 23 |
| | | | | | | |
| **2x** | Buy & Hold | 6.37% | 6.70% | 3.38% | -91.49% | 1 |
| **2x** | SMA 200 (ATR x2.5, T+2) | 9.81% | 10.02% | 6.43% | -63.45% | 11 |
| **2x** | **EMA 50/200** | **10.40%** | **10.50%** | **7.44%** | **-59.38%** | **12** |
| **2x** | VIX < 25 | 2.65% | 2.87% | 0.06% | -83.34% | 123 |
| **2x** | RSI 30/70 | 6.01% | 6.03% | 4.06% | -81.45% | 23 |
| | | | | | | |
| **1x** | Buy & Hold | 6.99% | 7.08% | 5.33% | -56.90% | 1 |
| **1x** | SMA 200 (ATR x2.5, T+2) | 7.49% | 7.66% | 5.48% | -34.45% | 11 |
| **1x** | **EMA 50/200** | **7.88%** | **8.08%** | **6.02%** | **-33.26%** | **12** |
| **1x** | VIX < 25 | 3.85% | 4.03% | 2.23% | -46.92% | 123 |
| **1x** | RSI 30/70 | 5.78% | 5.80% | 4.94% | -52.65% | 23 |

> **With T+2 confirmation, EMA 50/200 overtakes SMA 200 on the S&P 500 signal** — higher average TWR *and* a shallower max drawdown at every leverage tier (e.g. at 1x: 7.88% avg / -33.26% DD for EMA vs 7.49% avg / -34.45% DD for SMA). This reverses the pre-T+2 result, where SMA led on ^GSPC — consistent with the two-day confirmation delay costing SMA more in lost entry/exit timing than it saves in avoided whipsaws, though this comparison isn't a controlled same-window ablation (the window set itself also shifted between the pre- and post-T+2 numbers), so treat the causal read as a plausible hypothesis rather than a proven mechanism. `bot.py` runs the same T+2-confirmed SMA strategy on both its NASDAQ-100 and S&P 500 monitors for consistency — Table 1 continues to support that choice on the NASDAQ-100 signal, while this table shows EMA would historically have done better specifically on the S&P 500 signal.

---

### Table 3: NASDAQ-100 Returns + S&P 500 Signal — Lump Sum Performance
*Trade ^NDX (TQQQ) exposure but use ^GSPC (S&P 500) trend to determine in/out.*
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 3.10% | 3.84% | -9.09% | -99.98% | 1 |
| **3x** | SMA 200 (ATR x2.5, T+2) | 21.77% | 22.13% | 8.31% | -83.40% | 11 |
| **3x** | **EMA 50/200** | **22.93%** | **23.50%** | **9.02%** | **-88.61%** | **12** |
| **3x** | VIX < 25 | -1.84% | -1.10% | -10.36% | -99.85% | 124 |
| **3x** | RSI 30/70 | 3.74% | 3.64% | -0.89% | -99.39% | 23 |
| | | | | | | |
| **2x** | Buy & Hold | 11.17% | 11.83% | 1.54% | -98.95% | 1 |
| **2x** | SMA 200 (ATR x2.5, T+2) | 19.33% | 19.75% | 9.41% | -64.11% | 11 |
| **2x** | **EMA 50/200** | **20.41%** | **20.96%** | **10.12%** | **-70.83%** | **12** |
| **2x** | VIX < 25 | 3.48% | 4.20% | -3.20% | -98.17% | 124 |
| **2x** | RSI 30/70 | 8.17% | 8.01% | 5.52% | -92.72% | 23 |
| | | | | | | |
| **1x** | Buy & Hold | 11.65% | 12.06% | 6.12% | -82.99% | 1 |
| **1x** | SMA 200 (ATR x2.5, T+2) | 13.21% | 13.74% | 7.68% | -35.77% | 11 |
| **1x** | **EMA 50/200** | **13.89%** | **14.47%** | **8.17%** | **-40.11%** | **12** |
| **1x** | VIX < 25 | 5.52% | 6.03% | 1.55% | -83.44% | 124 |
| **1x** | RSI 30/70 | 7.99% | 7.88% | 6.60% | -64.15% | 23 |

> **vs. Table 1 (NDX own signal) and Table 2 (^GSPC own signal):** Table 3 inherits the same GSPC-signal
> dynamic seen in Table 2 — EMA 50/200 leads on average TWR, median TWR, and worst-case return at every
> leverage tier (e.g. at 1x: 13.89% vs SMA's 13.21% avg TWR). Drawdown, though, tells a different story
> than Table 2: SMA 200 (ATR x2.5) posts the shallower max drawdown at every tier (-83.40% vs -88.61% at
> 3x, -64.11% vs -70.83% at 2x, -35.77% vs -40.11% at 1x) — a consistent split by metric rather than the
> across-the-board EMA sweep seen in Table 2. This is the same returns-vs-drawdown trade-off Table 1
> shows, except here EMA's return edge is larger and extends to the worst-case floor at every tier too
> (not just some, as in Table 1), so EMA keeps the bold as the stronger overall pick on this signal —
> SMA remains the lower-drawdown alternative for anyone weighting capital preservation more heavily.


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
    * **T+2 Confirmation:** Requires a signal to persist for two consecutive trading days before acting, filtering out one-day spikes that would otherwise trigger a whipsaw trade.
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
