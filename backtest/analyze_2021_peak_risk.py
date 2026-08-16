"""
Risk-adjusted analysis of the 2021-peak simulation.

Runs the same three scenarios as simulate_2021_peak.py (QQQ buy & hold,
TQQQ buy & hold, and TQQQ traded on the bot's SMA 200 QQQ signal) but
reports Sharpe / Sortino / Calmar instead of just raw return.

The risk-free rate for Sharpe/Sortino is the simulator's own cash yield
(idle cash earns BR*0.8), so "excess return" means "return beyond what
sitting in cash would have earned in the same era" — internally consistent
with how the backtester already accounts for uninvested capital.
"""
import numpy as np
import pandas as pd

from backtest.strat_backtest import get_cached_signals, BuyAndHold, SMATrendFollowing
from backtest.risk_metrics import risk_report, sharpe_ratio, sortino_ratio, calmar_ratio
from backtest.simulate_2021_peak import find_2021_peak, latest_common_date


def equity_and_rf(base_ticker, signal_ticker, strategy, start, end, initial=10000):
    """Rebuild the strategy's daily equity curve plus the aligned per-day
    cash yield (risk-free rate), using the same return model as Backtester."""
    df = get_cached_signals(signal_ticker)
    df, _ = strategy.generate_signals(df)
    if signal_ticker != base_ticker:
        df_ret = get_cached_signals(base_ticker)
        for col in ["Daily_Return_1x", "Open2Close", "Overnight_Return"]:
            df[col] = df_ret[col]
        df = df.dropna(subset=["Daily_Return_1x"])
    df = df[(df.index >= start) & (df.index <= end)]

    in_mkt = df["in_market"].values.astype(bool)
    ret = np.nan_to_num(df["Daily_Return_1x"].values.astype(float))
    o2c = np.nan_to_num(df["Open2Close"].values.astype(float))
    ovn = np.nan_to_num(df["Overnight_Return"].values.astype(float))
    br = df["BR"].values.astype(float)
    cash_ret = (br * 0.8) / 252.0  # per-day risk-free proxy

    prev = np.empty(len(in_mkt), dtype=bool)
    prev[0] = False
    prev[1:] = in_mkt[:-1]
    entering = in_mkt & ~prev
    exiting = ~in_mkt & prev

    daily = np.where(in_mkt, ret, cash_ret)  # leverage=1: real TQQQ/QQQ price already leveraged
    daily[entering] = o2c[entering]
    daily[exiting] = ovn[exiting]

    equity = initial * np.cumprod(1 + daily)
    equity = np.insert(equity, 0, initial)  # prepend the starting value
    # rf aligned to the daily-return series (len = len(equity) - 1)
    rf_daily = cash_ret
    return equity, rf_daily


def main():
    peak_date, peak_price = find_2021_peak("QQQ")
    end_date = latest_common_date("QQQ", "TQQQ")
    years = (end_date - peak_date).days / 365.25

    print(f"2021 QQQ peak close: {peak_date.date()} @ ${peak_price:,.2f}")
    print(f"Simulating through:  {end_date.date()}  ({years:.2f} years)")
    print(f"Risk-free rate:      simulator cash yield (BR*0.8), era-accurate\n")

    scenarios = [
        ("QQQ  Buy & Hold",            "QQQ",  "QQQ",  BuyAndHold()),
        ("TQQQ Buy & Hold",            "TQQQ", "TQQQ", BuyAndHold()),
        ("TQQQ + SMA200 (QQQ signal)", "TQQQ", "QQQ",  SMATrendFollowing(sma_window=200, t2_confirmation=True)),
    ]

    rows = []
    for label, base, signal, strat in scenarios:
        equity, rf_daily = equity_and_rf(base, signal, strat, peak_date, end_date)
        rep = risk_report(equity, rf_daily=rf_daily)
        rows.append({
            "Scenario": label,
            "Ann. Return": rep["annual_return_pct"],
            "Ann. Vol": rep["ann_volatility_pct"],
            "Max DD": rep["max_drawdown_pct"],
            "Sharpe": rep["sharpe"],
            "Sortino": rep["sortino"],
            "Calmar": rep["calmar"],
        })

    df = pd.DataFrame(rows).set_index("Scenario")
    fmt = {
        "Ann. Return": "{:,.2f}%".format,
        "Ann. Vol": "{:,.2f}%".format,
        "Max DD": "{:,.2f}%".format,
        "Sharpe": "{:,.2f}".format,
        "Sortino": "{:,.2f}".format,
        "Calmar": "{:,.2f}".format,
    }
    with pd.option_context("display.width", 140, "display.max_columns", None):
        print(df.to_string(formatters=fmt))


if __name__ == "__main__":
    main()
