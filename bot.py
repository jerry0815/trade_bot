import yfinance as yf
import requests
import os
import datetime
import pandas as pd
import sys
from backtest.strat_backtest import *

def calculate_signal(data):
    """
    Core strategy function: Calculates signal based on triple filter (SMA + ATR + Confirmation)
    """
    atr_multiplier = 2.5
    sma200 = data['Close'].rolling(window=200).mean()
    
    # Calculate ATR (14-day)
    high = data['High']
    low = data['Low']
    prev_close = data['Close'].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()
    
    # Get latest data point (using only the last day)
    latest_close = float(data['Close'].iloc[-1].item())
    latest_sma = float(sma200.iloc[-1].item())
    latest_atr = float(atr.iloc[-1].item())
    
    # Calculate bands based on latest day
    upper_band = latest_sma + (latest_atr * atr_multiplier)
    lower_band = latest_sma - (latest_atr * atr_multiplier)
    
    is_bullish = (latest_close > upper_band)
    is_bearish = (latest_close < lower_band)
    
    if is_bullish:
        return "Bullish (UP)", "🚀 **Strong Signal: Hold/Add TQQQ + QQQ positions**"
    elif is_bearish:
        return "Bearish (DOWN)", "🚨 **Emergency Sell: Liquidate positions, move to SGOV for safety**"
    else:
        return "Neutral (Range)", "🛡️ **Waiting: Price within ATR channel, no action required**"

def generate_market_report(strategy, monitor_ticker="QQQ", leveraged_ticker="TQQQ"):
    """
    Fetches strategy stats and formats them into your report template.
    """

    state_file = "last_signal.txt"
    flag_file = "signal_changed.txt"
    #Get the stats dictionary from the strategy
    stats = strategy.get_live_stats(monitor_ticker, leveraged_ticker)
    trend = stats["trend"]

    last_signal = ""
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            last_signal = f.read().strip()
            
    signal_changed = (trend != last_signal)
    with open(flag_file, "w") as f:
        f.write("true" if signal_changed else "false")
    
    if signal_changed:
        with open(state_file, "w") as f:
            f.write(trend)
    
    change_alert = "🔄 **Signal Change Detected!**" if signal_changed else "✅ Status: No change in signal."

    date_str = pd.Timestamp.now().strftime("%Y-%m-%d")

    # We use .get(key, default) for custom fields so the report doesn't crash 
    # if a strategy doesn't provide them.
    message = (
        f"📅 **Market Monitor Report ({date_str})**\n"
        f"{change_alert}\n"
        f"--------------------------\n"
        f"📊 **Monitor Ticker ({monitor_ticker}):** {stats['qqq_price']:.2f}\n"
        f"⚡ **Leveraged Ticker ({leveraged_ticker}):** {stats['tqqq_price']:.2f}\n"
        f"📈 **Trend Line (200-Day SMA):** {stats.get('current_sma', 0.0):.2f}\n"
        f"💡 **Current Market Status:** **{stats.get('trend', 'N/A')}**\n"
        f"--------------------------\n"
        f"💰 **Asset Allocation Status:**\n"
        f"• Offensive Positions (TQQQ/QQQ): Adjust based on signal\n"
        f"• Defensive Positions (SGOV): Suggested Hold (for hedging)\n"
        f"--------------------------\n"
        f"🚩 **Execution Action:** {stats['action']}"
    )
    
    return message

def run_bot():
    webhook_url = os.environ.get("DISCORD_WEBHOOK")

    strat = SMATrendFollowing(sma_window=200)
    message = generate_market_report(strat)
    
    # Send to Discord
    if webhook_url:
        requests.post(webhook_url, json={"content": message})
    else:
        print(message)
    
    # Exit successfully
    sys.exit(0)

if __name__ == "__main__":
    run_bot()