"""
Simulates: "I bought at the 2021 high point" — what happens if you buy TQQQ
(or QQQ) right at the peak before the 2022 bear market, and hold to today,
vs. running the repo's SMA-200 (ATR x2.5, T+2) trend-following strategy
on the same entry.

Uses real QQQ/TQQQ price history (yfinance), not the synthetic ^NDX*3
leverage model used for the README's 26-year rolling tables — this answers
"what would have actually happened to my money" with the real ETF.

Run:
    python backtest/simulate_2021_high_entry.py

Requires network access to Yahoo Finance (blocked in some sandboxed CI
environments — run this on a machine with normal internet access).
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backtest.strat_backtest import (
    BuyAndHold, SMATrendFollowing, Backtester, get_cached_data,
)


def find_2021_high(ticker="QQQ"):
    """Finds the actual all-time-high close within 2021 (the pre-bear-market peak)."""
    df = get_cached_data(ticker)
    window = df.loc["2021-01-01":"2021-12-31"]
    peak_date = window["Close"].idxmax()
    peak_price = float(window["Close"].max())
    return peak_date, peak_price


def run_scenario(base_ticker, signal_ticker, strategy, start_date, end_date, label):
    bt = Backtester(
        base_ticker=base_ticker,
        signal_ticker=signal_ticker,
        start_date=start_date.strftime("%Y-%m-%d"),
        period_years=1,          # placeholder, overridden below
        leverage=1,              # real ticker prices already embed leverage/expense drag
        expense_ratio=0.0,
        initial_fund=10000,
        verbose=False,
    )
    bt.end_dt = end_date         # run to "today" exactly, instead of a fixed offset
    res = bt.run(strategy)
    if res is None:
        print(f"[{label}] No data returned — check date range / ticker availability.")
        return None

    print(f"\n=== {label} ===")
    print(f"Entry date:      {start_date.date()}")
    print(f"Final value:     ${res['final_value']:,.2f}  (on $10,000)")
    print(f"Total ROI:       {res['total_roi']:,.2f}%")
    print(f"Annualized TWR:  {res['strategy_twr']:,.2f}%")
    print(f"Max drawdown:    {res['max_drawdown']:.2f}%")
    print(f"Lowest value:    ${res['min_value']:,.2f}")
    print(f"Total trades:    {res.get('total_trades', 0)}")
    return res


def main():
    qqq_peak_date, qqq_peak_price = find_2021_high("QQQ")
    tqqq_peak_date, tqqq_peak_price = find_2021_high("TQQQ")

    print(f"QQQ 2021 high:  {qqq_peak_date.date()}  @ ${qqq_peak_price:,.2f}")
    print(f"TQQQ 2021 high: {tqqq_peak_date.date()} @ ${tqqq_peak_price:,.2f}")

    # Use QQQ's peak date as "the 2021 high point" entry — it's what the
    # live bot actually monitors for signal generation (monitor_ticker=QQQ).
    entry_date = qqq_peak_date
    today = pd.Timestamp.today().normalize()

    strategy = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    buy_hold = BuyAndHold()

    # Scenario A: lump-sum buy-and-hold TQQQ from the 2021 high, no exits ever.
    run_scenario("TQQQ", "TQQQ", buy_hold, entry_date, today,
                 "Buy & Hold TQQQ (bought at 2021 high, never sold)")

    # Scenario B: SMA-200 (ATR x2.5, T+2) strategy — signal from QQQ, traded on TQQQ.
    run_scenario("TQQQ", "QQQ", strategy, entry_date, today,
                 "SMA-200 Trend Strategy (QQQ signal, traded on TQQQ)")

    # Scenario C: lump-sum buy-and-hold QQQ (unleveraged) from the same date.
    run_scenario("QQQ", "QQQ", buy_hold, entry_date, today,
                 "Buy & Hold QQQ (unleveraged, bought at 2021 high)")


if __name__ == "__main__":
    main()
