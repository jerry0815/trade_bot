import yfinance as yf
import requests
import os
import datetime
import pandas as pd

def calculate_signal(data):
    """
    Core strategy function: Calculates signal based on triple filter (SMA + ATR + Confirmation)
    Returns: "Bullish", "Bearish", or "Neutral" and the corresponding action
    """
    # 1. Calculate 200-Day SMA
    sma200 = data['Close'].rolling(window=200).mean()
    
    # 2. Calculate 14-Day ATR
    high = data['High']
    low = data['Low']
    prev_close = data['Close'].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()
    
    # 3. Triple Filter Confirmation (Check last 3 days)
    last_3_days = data.iloc[-3:]
    last_3_sma = sma200.iloc[-3:]
    last_3_atr = atr.iloc[-3:]
    
    # Logic: Signal confirmed only if all 3 days meet the criteria
    is_bullish = all(last_3_days['Close'] > (last_3_sma + last_3_atr))
    is_bearish = all(last_3_days['Close'] < (last_3_sma - last_3_atr))
    
    if is_bullish:
        return "Bullish (UP)", "🚀 **Strong Signal: Hold/Add TQQQ + QQQ positions**"
    elif is_bearish:
        return "Bearish (DOWN)", "🚨 **Emergency Sell: Liquidate positions, move to SGOV for safety**"
    else:
        return "Neutral (Range)", "🛡️ **Waiting: Price within ATR channel, no action required**"

def run_bot():
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    ticker = "QQQ"
    
    # Fetch data
    data = yf.download(ticker, period="1y") 
    
    # Execute strategy
    trend, action = calculate_signal(data)
    
    # Get price info
    current_price = float(data['Close'].iloc[-1])
    current_sma = float(data['Close'].rolling(window=200).mean().iloc[-1])
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Format notification message
    message = (
        f"📅 **Market Monitor Report ({date_str})**\n"
        f"--------------------------\n"
        f"Ticker: {ticker} (Price: {current_price:.2f})\n"
        f"200-Day SMA: {current_sma:.2f}\n"
        f"Market Trend: **{trend}**\n"
        f"--------------------------\n"
        f"🚩 **Action Suggestion:** {action}"
    )
    
    # Send to Discord
    if webhook_url:
        requests.post(webhook_url, json={"content": message})
    else:
        print(message)

if __name__ == "__main__":
    run_bot()