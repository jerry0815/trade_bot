import requests
import os
import pandas as pd
import sys
# Ensure Windows terminal doesn't crash when printing emojis
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from backtest.strat_backtest import (SMATrendFollowing, DualSignalAgreement, _download_with_retry,
                                     get_current_defensive_rotation, get_cached_data)

# DualSignalAgreement reads ^NDX/^GSPC (and ^VIX) through get_cached_data, which
# prefers the committed data/*.csv snapshot. That snapshot is frozen at the date
# it was saved, so a live report must re-download these every run or the
# recommended action and trailing stop are computed on stale prices.
LIVE_INDEX_TICKERS = ("^NDX", "^GSPC", "^VIX")


def refresh_live_index_data():
    for ticker in LIVE_INDEX_TICKERS:
        get_cached_data(ticker, refresh=True, persist=False)

def status_note(trend, stats):
    """Explains a Status that disagrees with the Duration line. Status is
    today's close against the ATR band; the position only flips after the
    T+2 confirmation, so a single close outside the band leaves it as is."""
    if stats.get("signal_changed"):
        verb = "BUY" if stats["action"].startswith("BUY") else "SELL"
        return f" — confirmed, {verb} at next open"
    invested_next = stats.get("action", "").startswith("BUY")
    if trend == "BEARISH" and invested_next:
        return " — below lower band, sell not confirmed yet (needs 2 closes in a row)"
    if trend == "BULLISH" and not invested_next:
        return " — above upper band, buy not confirmed yet (needs 2 closes in a row)"
    return ""


def generate_market_report(strategy, strategy_d, strategy_d_notax, monitor_ticker="QQQ", leveraged_ticker="TQQQ", sp500_ticker="SPY"):
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

    # D's combined verdict (dual-signal agreement + ^GSPC trailing stop).
    # Signals computed on ^NDX/^GSPC internally; monitor ticker only supplies
    # the base price fields, which we don't use here.
    stats_d = strategy_d.get_live_stats(sp500_ticker, leveraged_ticker, data=shared_data)
    ts = stats_d["trailing_stop"]

    # Taxable-account verdict: the SAME dual-signal agreement WITHOUT the
    # trailing stop. Table 8 (docs/taxable-account-2026-08-06.md) found the
    # stop's extra trades realize short-term gains and, after tax, it turns
    # into a net-negative return trade (dual-signal 23.61% after-tax with the
    # stop OFF vs 19.82% with it ON) — so a taxable account should skip it.
    stats_d_notax = strategy_d_notax.get_live_stats(sp500_ticker, leveraged_ticker, data=shared_data)

    # A change is an account's recommended action for the next open differing
    # from the position it held today (a fresh entry, or an exit including a
    # stop-triggered one), so the alert fires the evening the trade is due.
    changed = [name for name, st in (("tax-advantaged", stats_d), ("taxable", stats_d_notax))
               if st["signal_changed"]]
    if changed:
        change_alert = f"🔄 **Signal Change Detected!** Trade at next open: {' and '.join(changed)} account"
    else:
        change_alert = "✅ Status: No change in signal."

    date_str = pd.Timestamp.now().strftime("%Y-%m-%d")

    def format_signal_section(title, ticker, stats):
        state_label = stats.get("position", "N/A")
        streak_days = stats.get("days_in_current_state", 0)
        state_since = stats.get("state_since", "N/A")
        
        trend = stats.get('trend', 'N/A')
        emoji = "🟩" if trend == "BULLISH" else "🟥" if trend == "BEARISH" else "🟨"
        trend_note = status_note(trend, stats)
        
        upper = stats.get('upper_bound', 0.0)
        lower = stats.get('lower_bound', 0.0)
        
        return (
            f"📈 **{title} ({ticker})**\n"
            f"• Price: {stats['qqq_price']:.2f} | SMA(200): {stats.get('current_sma', 0.0):.2f}\n"
            f"• ATR Channel: {lower:.2f} - {upper:.2f}\n"
            f"• Status: **{trend}** {emoji}{trend_note}\n"
            f"• Duration: {streak_days} trading days {state_label} (since {state_since})"
        )

    def format_trailing_stop(ts):
        header = "🛑 **TRAILING STOP (S&P 500, 8% / 60d)**"
        if ts["state"] in ("holding", "triggered"):
            price_lines = (
                f"• Peak since entry: {ts['peak']:.2f} | Current: {ts['current']:.2f}\n"
                f"• Drop from peak: {ts['drop_pct']:.2f}% "
                f"(trigger at -8.00%, {ts['distance_pct']:.2f}% to go)\n"
            )
        else:
            price_lines = "• Peak since entry: n/a | Current: n/a\n"
        status = {
            "holding":   "Holding",
            "triggered": "SELL — S&P fell 8% from peak",
            "cooldown":  f"In cash — stop cooldown, {ts['cooldown_left']} trading days until re-entry allowed",
            "inactive":  "In cash — no position",
        }[ts["state"]]
        return f"{header}\n{price_lines}• Status: {status}"

    def changed_tag(stats):
        return " 🔄 (new — trade at next open)" if stats["signal_changed"] else ""

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
        f"ⓘ Recommended actions are for the next market open.\n"
        f"{change_alert}\n"
        f"--------------------------\n"
        f"{format_signal_section('PRIMARY SIGNAL - S&P 500', sp500_ticker, stats_sp500)}\n\n"
        f"{format_signal_section('SECONDARY SIGNAL - NASDAQ', monitor_ticker, stats_ndx)}\n"
        f"--------------------------\n"
        f"💰 **ASSET ALLOCATION**\n"
        f"• Offensive ({leveraged_ticker}): {stats_ndx['leveraged_price']:.2f} (Adjust based on primary signal)\n"
        f"{def_msg}\n"
        f"--------------------------\n"
        f"{format_trailing_stop(ts)}\n"
        f"--------------------------\n"
        f"🚩 **RECOMMENDED ACTION**\n"
        f"• Tax-advantaged account (IRA/401k/Roth) — dual-signal + trailing stop: **{stats_d['action']}**{changed_tag(stats_d)}\n"
        f"• Taxable account — dual-signal, no trailing stop: **{stats_d_notax['action']}**{changed_tag(stats_d_notax)}\n"
        f"  ⓘ Taxable drops the stop: after tax its extra trades realize short-term gains and hurt returns (Table 8)."
    )
    
    return message

def run_bot():
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    refresh_live_index_data()

    strat = SMATrendFollowing(sma_window=200, t2_confirmation=True)
    strat_d = DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                                  trailing_stop_pct=0.08, trailing_stop_cooldown_days=60)
    # Taxable-account variant: same dual-signal agreement, no trailing stop
    # (see the RECOMMENDED ACTION note in generate_market_report).
    strat_d_notax = DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False)
    message = generate_market_report(strat, strat_d, strat_d_notax)
    
    # Send to Discord
    if webhook_url:
        requests.post(webhook_url, json={"content": message})
    else:
        print(message)
    
    # Exit successfully
    sys.exit(0)

if __name__ == "__main__":
    run_bot()