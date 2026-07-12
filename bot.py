import requests
import os
import pandas as pd
import sys
# Ensure Windows terminal doesn't crash when printing emojis
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from backtest.strat_backtest import SMATrendFollowing

def generate_market_report(strategy, monitor_ticker="QQQ", leveraged_ticker="TQQQ", sp500_ticker="SPY"):
    """
    Fetches strategy stats and formats them into your report template.
    """

    state_file = "last_signal.txt"
    flag_file = "signal_changed.txt"
    
    # Get the stats dictionary from the strategy for both indices
    stats_ndx = strategy.get_live_stats(monitor_ticker, leveraged_ticker)
    stats_sp500 = strategy.get_live_stats(sp500_ticker, sp500_ticker) # Use SPY for both to avoid extra fetching
    
    # We use the S&P 500 trend as the primary signal based on our cross-signal experiment
    primary_trend = stats_sp500["trend"]
    secondary_trend = stats_ndx["trend"]

    last_signal = ""
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            last_signal = f.read().strip()
            
    # Combine trends to track changes in either signal
    current_signal_state = f"{primary_trend}_{secondary_trend}"
    signal_changed = (current_signal_state != last_signal)
    
    if signal_changed:
        with open(flag_file, "w") as f:
            f.write("true")
        with open(state_file, "w") as f:
            f.write(current_signal_state)
    
    change_alert = "🔄 **Signal Change Detected!**" if signal_changed else "✅ Status: No change in signal."

    date_str = pd.Timestamp.now().strftime("%Y-%m-%d")

    def format_signal_section(title, ticker, stats):
        state_label = "invested" if stats.get("action", "").startswith("BUY") else "in cash"
        streak_days = stats.get("days_in_current_state", 0)
        state_since = stats.get("state_since", "N/A")
        
        trend = stats.get('trend', 'N/A')
        emoji = "🟩" if trend == "BULLISH" else "🟥" if trend == "BEARISH" else "🟨"
        
        return (
            f"📈 **{title} ({ticker})**\n"
            f"• Price: {stats['qqq_price']:.2f} | SMA(200): {stats.get('current_sma', 0.0):.2f}\n"
            f"• Status: **{trend}** {emoji}\n"
            f"• Duration: {streak_days} trading days {state_label} (since {state_since})"
        )

    message = (
        f"📅 **Market Monitor Report ({date_str})**\n"
        f"{change_alert}\n"
        f"--------------------------\n"
        f"{format_signal_section('PRIMARY SIGNAL - S&P 500', sp500_ticker, stats_sp500)}\n\n"
        f"{format_signal_section('SECONDARY SIGNAL - NASDAQ', monitor_ticker, stats_ndx)}\n"
        f"--------------------------\n"
        f"💰 **ASSET ALLOCATION**\n"
        f"• Offensive ({leveraged_ticker}): {stats_ndx['tqqq_price']:.2f} (Adjust based on primary signal)\n"
        f"• Defensive (SGOV): Suggested Hold (for hedging)\n"
        f"--------------------------\n"
        f"🚩 **RECOMMENDED ACTION:** {stats_sp500['action']}"
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