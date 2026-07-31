"""
One-off simulation: buy TQQQ at the 2021 market peak and trade it with the
bot's live SMA 200 (ATR x2.5, T+2) strategy (signal from QQQ, same as
bot.py), vs. simply buying QQQ and holding, vs. buying TQQQ and holding.

All three start on the same calendar day -- the date QQQ closed at its
highest price in 2021 -- and run to the latest available trading day.
Uses real QQQ/TQQQ price history (not the synthetic ^NDX*3 model used by
the rolling 26-year tables in the README).
"""
import pandas as pd

from backtest.strat_backtest import Backtester, BuyAndHold, SMATrendFollowing, get_cached_data


def find_2021_peak(ticker="QQQ"):
    """Returns the date + price of `ticker`'s highest close during 2021."""
    df = get_cached_data(ticker)
    year_df = df.loc["2021-01-01":"2021-12-31"]
    peak_date = year_df["Close"].idxmax()
    peak_price = float(year_df["Close"].loc[peak_date])
    return peak_date, peak_price


def latest_common_date(*tickers):
    return min(get_cached_data(t).index.max() for t in tickers)


def run_from_peak(base_ticker, signal_ticker, strategy, start_date, end_date):
    bt = Backtester(
        base_ticker=base_ticker,
        signal_ticker=signal_ticker,
        start_date=start_date,
        period_years=1,       # placeholder; overridden by end_dt below
        leverage=1,           # TQQQ/QQQ prices are already the real traded product
        expense_ratio=0.0,    # ...so don't double-apply a synthetic drag
        initial_fund=10000,
        verbose=False,
    )
    bt.end_dt = end_date  # extend the window to all available data past the peak
    return bt.run(strategy)


def main():
    peak_date, peak_price = find_2021_peak("QQQ")
    end_date = latest_common_date("QQQ", "TQQQ")
    years = (end_date - peak_date).days / 365.25

    print(f"2021 QQQ peak close: {peak_date.date()} @ ${peak_price:,.2f}")
    print(f"Simulating through:  {end_date.date()}  ({years:.2f} years)\n")

    runs = [
        ("QQQ  Buy & Hold",            "QQQ",  "QQQ",  BuyAndHold()),
        ("TQQQ Buy & Hold",            "TQQQ", "TQQQ", BuyAndHold()),
        ("TQQQ + SMA200 (QQQ signal)", "TQQQ", "QQQ",  SMATrendFollowing(sma_window=200, t2_confirmation=True)),
    ]

    rows = []
    for label, base, signal, strat in runs:
        res = run_from_peak(base, signal, strat, peak_date, end_date)
        rows.append({
            "Scenario": label,
            "Final Value ($10k start)": res["final_value"],
            "Total ROI": res["total_roi"],
            "Annualized (TWR)": res["strategy_twr"],
            "Max Drawdown": res["max_drawdown"],
            "Trades": res["total_trades"],
        })

    df = pd.DataFrame(rows).set_index("Scenario")
    with pd.option_context(
        "display.float_format", lambda x: f"{x:,.2f}",
        "display.width", 120,
        "display.max_columns", None,
    ):
        print(df)


if __name__ == "__main__":
    main()
