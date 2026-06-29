# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. By utilizing a **200-Day Simple Moving Average (200 SMA)**, the system provides real-time trend assessment to maximize compound growth during bull markets and execute defensive exit strategies before systemic bear markets.



---

### **Strategy Logic**
The system acts as a disciplined guardrail for your investment:
* **Bullish Signal (QQQ > 200 SMA):** The system suggests maintaining long positions in QQQ/TQQQ to capture leveraged market growth.
* **Bearish Signal (QQQ < 200 SMA):** The system triggers a defensive alert, suggesting a move to cash or short-term treasury bills (e.g., SGOV/BIL) to avoid catastrophic drawdown risks.
* **Disciplined Execution:** By automating the calculation daily, it removes emotional bias and ensures strict adherence to the moving average discipline.

---

### **System Architecture**
* **Automation:** Powered by **GitHub Actions**, which runs the script automatically after market close.
* **Data Engine:** Uses `yfinance` to fetch reliable, real-time market data.
* **Notification:** Integrated with **Discord Webhooks** for instant, actionable trading recommendations.

---

### **Getting Started**
1. **Clone/Fork** this repository.
2. **Configure Secrets:** Navigate to `Settings` > `Secrets and variables` > `Actions` and add your `DISCORD_WEBHOOK` URL.
3. **Dependencies:** Install the required libraries via:
   ```bash
   pip install -r requirements.txt