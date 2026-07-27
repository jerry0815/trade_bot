import requests
import os
import pandas as pd
import sys
# Ensure Windows terminal doesn't crash when printing emojis
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from backtest.strat_backtest import SMATrendFollowing, _download_with_retry, get_current_defensive_rotation

def generate_market_report(strategy, monitor_ticker="QQQ", leveraged_ticker="TQQQ", sp500_ticker="SPY"):
    """
    Fetches strategy stats and formats them into your report template.
    Downloads all required tickers in a single yf.download call to avoid
    hitting Yahoo Finance rate limits from back-to-back requests.
    """

    # Single download covering all tickers needed by both strategy calls.
    all_tickers = f"{monitor_ticker} {leveraged_ticker} {sp500_ticker} ^VIX KMLM TLT GLD SHY"
    shared_data = _download_with_retry(all_tickers)

    # Get the stats dictionary from the strategy for both indices
    stats_ndx   = strategy.get_live_stats(monitor_ticker, leveraged_ticker, data=shared_data)
    stats_sp500 = strategy.get_live_stats(sp500_ticker, sp500_ticker,       data=shared_data)
    
    # Get defensive rotation status
    def_rot = get_current_defensive_rotation(shared_data)
    
    # Check if either signal changed from yesterday
    signal_changed = stats_sp500["trend_changed"] or stats_ndx["trend_changed"]
    
    change_alert = "🔄 **Signal Change Detected!**" if signal_changed else "✅ Status: No change in signal."

    date_str = pd.Timestamp.now().strftime("%Y-%m-%d")

    def format_signal_section(title, ticker, stats):
        state_label = "invested" if stats.get("action", "").startswith("BUY") else "in cash"
        streak_days = stats.get("days_in_current_state", 0)
        state_since = stats.get("state_since", "N/A")
        
        trend = stats.get('trend', 'N/A')
        emoji = "🟩" if trend == "BULLISH" else "🟥" if trend == "BEARISH" else "🟨"
        
        upper = stats.get('upper_bound', 0.0)
        lower = stats.get('lower_bound', 0.0)
        
        return (
            f"📈 **{title} ({ticker})**\n"
            f"• Price: {stats['qqq_price']:.2f} | SMA(200): {stats.get('current_sma', 0.0):.2f}\n"
            f"• ATR Channel: {lower:.2f} - {upper:.2f}\n"
            f"• Status: **{trend}** {emoji}\n"
            f"• Duration: {streak_days} trading days {state_label} (since {state_since})"
        )

    winner = def_rot['winner']
    display_winner = "SHY / SGOV" if winner == "SHY" else winner
    moms = def_rot['momentums']
    
    def_msg = (
        f"• Defensive (Dynamic Rotation): Hold **{display_winner}** during Sell signals\n"
        f"  - KMLM: {moms.get('KMLM', 0.0)*100:+.2f}%\n"
        f"  - TLT:  {moms.get('TLT', 0.0)*100:+.2f}%\n"
        f"  - GLD:  {moms.get('GLD', 0.0)*100:+.2f}%\n"
        f"  - SHY / SGOV:  {moms.get('SHY', 0.0)*100:+.2f}%"
    )

    message = (
        f"📅 **Market Monitor Report ({date_str})**\n"
        f"{change_alert}\n"
        f"--------------------------\n"
        f"{format_signal_section('PRIMARY SIGNAL - S&P 500', sp500_ticker, stats_sp500)}\n\n"
        f"{format_signal_section('SECONDARY SIGNAL - NASDAQ', monitor_ticker, stats_ndx)}\n"
        f"--------------------------\n"
        f"💰 **ASSET ALLOCATION**\n"
        f"• Offensive ({leveraged_ticker}): {stats_ndx['leveraged_price']:.2f} (Adjust based on primary signal)\n"
        f"{def_msg}\n"
        f"--------------------------\n"
        f"🚩 **RECOMMENDED ACTION:** {stats_sp500['action']}"
    )
    
    return message

def run_bot():
    webhook_url = os.environ.get("DISCORD_WEBHOOK")

    strat = SMATrendFollowing(sma_window=200, atr_window=50, t2_confirmation=True)
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