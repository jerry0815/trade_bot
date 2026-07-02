# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. By utilizing a **200-Day Simple Moving Average (200 SMA)**, the system provides real-time trend assessment to maximize compound growth during bull markets and execute defensive exit strategies before systemic bear markets.

---

### **Strategy Logic**
The system acts as a disciplined guardrail for your investment:
* **Bullish Signal:** The system suggests maintaining long positions in QQQ/TQQQ to capture leveraged market growth.
* **Bearish Signal:** The system triggers a defensive alert, suggesting a move to cash or short-term treasury bills (e.g., SGOV/BIL) to avoid catastrophic drawdown risks.
* **Disciplined Execution:** By automating the calculation daily, it removes emotional bias and ensures strict adherence to the moving average discipline.

### Table 1: NASQ100 Lump Sum Performance
*Backtest Parameters: 26-year rolling periods starting from 1980-01-15.*
*Initial Investment: $10,000*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Max DD | Avg Trades |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **3x** | Buy & Hold | 2.01% | 1.85% | -7.44% | -99.97% | **0.0** |
| **3x** | **SMA 200 (ATR x2.5)** | **20.69%** | **21.93%** | **11.71%** | **-81.87%** | 24.0 |
| **3x** | EMA 50/200 | 19.05% | 20.21% | 9.60% | -91.31% | 23.0 |
| **3x** | VIX < 25 | -3.03% | -2.84% | -10.13% | -99.85% | 169.0 |
| **3x** | RSI 30/70 | -6.87% | -6.96% | -14.74% | -99.53% | 36.0 |
| | | | | | | |
| **2x** | Buy & Hold | 10.45% | 10.16% | 2.77% | -98.78% | **0.0** |
| **2x** | **SMA 200 (ATR x2.5)** | **18.96%** | **19.77%** | 11.76% | **-62.49%** | 24.0 |
| **2x** | EMA 50/200 | 18.26% | 18.81% | **12.19%** | -70.29% | 23.0 |
| **2x** | VIX < 25 | 2.67% | 2.86% | -3.07% | -98.24% | 169.0 |
| **2x** | RSI 30/70*| 0.93% | 0.81% | -4.45% | -95.79% | 36.0 |
| | | | | | | |
| **1x** | Buy & Hold | 11.49% | 11.61% | 6.76% | -82.67% | **0.0** |
| **1x** | **SMA 200 (ATR x2.5)** | **13.33%** | 13.42% | 8.87% | **-35.76%** | 24.0 |
| **1x** | EMA 50/200 | 13.23% | **13.53%** | **9.29%** | -39.94% | 23.0 |
| **1x** | VIX < 25 | 5.23% | 5.54% | 1.59% | -83.44% | 169.0 |
| **1x** | RSI 30/70 | 4.60% | 4.52% | 2.30% | -72.05% | 36.0 |

### Table 2: SP500 Lump Sum Performance
*Calculation: Annualized Return / Annualized Volatility (Sharpe Ratio approximation)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Max DD | Avg Trades |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **3x** | Buy & Hold | 2.75% | 3.33% | -3.73% | -98.86% | 0.0 |
| **3x** | **SMA 200 (ATR x2.5)** | **13.25%** | **13.16%** | **9.68%** | **-58.57%** | 19.0 |
| **3x** | EMA 50/200 | 11.24% | 10.89% | 6.93% | -79.37% | 20.0 |
| | | | | | | |
| **2x** | Buy & Hold | 6.42% | 6.63% | 2.41% | -91.49% | 0.0 |
| **2x** | **SMA 200 (ATR x2.5)** | **11.26%** | **11.27%** | 9.13% | **-43.04%** | 19.0 |
| **2x** | EMA 50/200 | 10.39% | 10.42% | 10.39% | -59.38% | 20.0 |
| | | | | | | |
| **1x** | Buy & Hold | 7.18% | 7.24% | 5.33% | -56.90% | 0.0 |
| **1x** | **SMA 200 (ATR x2.5)** | **8.34%** | **8.48%** | 6.75% | **-23.55%** | 19.0 |
| **1x** | EMA 50/200 | 8.13% | 8.36% | 9.29% | -33.26% | 20.0 |


---

### **Strategy Research & Theoretical Basis**
This bot implements a **Trend-Following Strategy** enhanced with a **Triple-Filter System** to mitigate "Whipsaw" (false signals). This methodology is supported by key quantitative finance principles:

1. **Trend-Filtering for Leveraged ETFs:** Leveraged ETFs are subject to *Volatility Decay*. Research (e.g., Meb Faber) suggests that 200-day trend filters effectively "clip the left tail" of risk, preventing catastrophic drawdowns during secular bear markets.
2. **The Triple-Filter Mechanism:**
    * **SMA 200:** Identifies the long-term regime (Bull vs. Bear).
    * **ATR (Average True Range) Filter:** Dynamically adjusts the "No-Trade Zone" based on current market volatility, preventing the bot from overreacting to minor noise in stable markets.
    * **Time-Confirmation:** Requires a **3-day consecutive close** beyond the ATR-adjusted channel to confirm trend reversals, significantly reducing false positives.
3. **Core Objective:** To improve **Risk-Adjusted Returns (Sharpe Ratio)** by preserving capital during systemic failures rather than attempting to time minor market tops.

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
4. **Automation:** The workflow file .github/workflows/daily_check.yml is pre-configured to run automatically every trading day.

### **Risk Disclaimer**
This project is for educational and monitoring purposes only. Leveraged ETFs (such as TQQQ) are highly volatile instruments. The 200 SMA strategy is designed to mitigate long-term systemic risk but may face "whipsaw" losses during sideways or consolidating markets. Please assess your risk tolerance before executing real-world trades based on these signals.