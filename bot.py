import yfinance as yf
import requests
import os
import datetime

def run_bot():
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    ticker = "QQQ"
    
    # Fetch 1 year of data to ensure 200 SMA calculation
    data = yf.download(ticker, period="1y") 
    
    # Calculate 200 Day SMA
    sma200 = float(data['Close'].rolling(window=200).mean().iloc[-1])
    current_price = float(data['Close'].iloc[-1])
    
    # Determine signal
    if current_price > sma200:
        trend = "多頭 (UP)"
        action = "✅ **持有 QQQ/TQQQ 部位 (維持策略)**"
    else:
        trend = "空頭 (DOWN)"
        action = "⚠️ **防守訊號：請賣出 TQQQ，轉入 SGOV (現金停泊)**"
    
    # Format message
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    message = (
        f"**市場監控報告 ({date_str})**\n"
        f"--------------------------\n"
        f"標的: {ticker} (價格: {current_price:.2f})\n"
        f"200日均線: {sma200:.2f}\n"
        f"目前狀態: **{trend}**\n"
        f"--------------------------\n"
        f"🚩 **操作建議:** {action}"
    )
    
    # Send to Discord
    requests.post(webhook_url, json={"content": message})

if __name__ == "__main__":
    run_bot()