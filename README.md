# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. By utilizing a **200-Day Simple Moving Average (200 SMA)**, the system provides real-time trend assessment to maximize compound growth during bull markets and execute defensive exit strategies before systemic bear markets.

---

### **Strategy Logic**
The system acts as a disciplined guardrail for your investment:
* **Bullish Signal:** The system suggests maintaining long positions in QQQ/TQQQ to capture leveraged market growth.
* **Bearish Signal:** The system triggers a defensive alert, suggesting a move to cash or short-term treasury bills (e.g., SGOV/BIL) to avoid catastrophic drawdown risks.
* **Disciplined Execution:** By automating the calculation daily, it removes emotional bias and ensures strict adherence to the moving average discipline.

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