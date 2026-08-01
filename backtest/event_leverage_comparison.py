"""
Event-relative comparison of the live SMA strategy (S&P 500 signal,
T+2 on), its VIX-adaptive variant (T+2 bypassed on VIX>30 days), and
Buy & Hold, across both ^NDX (QQQ/TQQQ family) and ^GSPC (S&P 500
family) as the base ticker, at 1x/2x/3x leverage — for each of the 5
known market crises this project already tracks.

Same "event-relative" methodology as the earlier ad-hoc analysis: each
event's decline is measured from the equity value at/just-before the
event's well-known start date to the local trough within the event
window, independent of whether an earlier, still-unresolved drawdown was
in progress — so one crisis's effect isn't hidden inside another's.

Run manually:
    python backtest/event_leverage_comparison.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing, BuyAndHold, Backtester

OUTPUT_PATH = REPO_ROOT / "backtest" / "event_leverage_output.md"

TICKERS = [("QQQ / ^NDX", "^NDX"), ("S&P 500 / ^GSPC", "^GSPC")]
LEVERAGE_CONFIGS = [
    {"name": "1x", "leverage": 1, "expense": 0.0020},
    {"name": "2x", "leverage": 2, "expense": 0.0095},
    {"name": "3x", "leverage": 3, "expense": 0.0095},
]

EVENTS = [
    ("Black Monday 1987",    "1987-08-25", "1987-12-04"),
    ("Dot-com crash",        "2000-03-24", "2002-10-09"),
    ("2008 GFC",             "2007-10-09", "2009-03-09"),
    ("COVID crash",          "2020-02-19", "2020-03-23"),
    ("2022 rate-shock bear", "2022-01-03", "2022-10-12"),
]


def get_equity_curve(strategy, base_ticker, leverage, expense_ratio):
    env = Backtester(
        base_ticker=base_ticker, signal_ticker="^GSPC", start_date="1986-04-29",
        period_years=40, leverage=leverage, expense_ratio=expense_ratio,
        initial_fund=10000, verbose=False,
    )
    res = env.run(strategy)
    return res["equity_curve"] if res else None


def event_decline(equity, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start < equity.index[0]:
        return None
    local_peak_date = equity.loc[:start].index[-1]
    local_peak = equity.loc[local_peak_date]
    trough = equity.loc[start:end].min()
    return (trough / local_peak - 1) * 100


VIX_BYPASS_THRESHOLD = 30  # best single threshold found in the initial NDX/3x sweep


if __name__ == "__main__":
    rows = []
    for ticker_label, ticker in TICKERS:
        for cfg in LEVERAGE_CONFIGS:
            print(f"Running {ticker_label} @ {cfg['name']}...")
            strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
            strat_vix = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                                           vix_threshold=VIX_BYPASS_THRESHOLD)
            bench = BuyAndHold()
            eq_strat = get_equity_curve(strat, ticker, cfg["leverage"], cfg["expense"])
            eq_vix = get_equity_curve(strat_vix, ticker, cfg["leverage"], cfg["expense"])
            eq_bh = get_equity_curve(bench, ticker, cfg["leverage"], cfg["expense"])

            for event_name, start, end in EVENTS:
                strat_decline = event_decline(eq_strat, start, end) if eq_strat is not None else None
                vix_decline = event_decline(eq_vix, start, end) if eq_vix is not None else None
                bh_decline = event_decline(eq_bh, start, end) if eq_bh is not None else None
                if strat_decline is None or vix_decline is None or bh_decline is None:
                    continue
                rows.append({
                    "Ticker": ticker_label,
                    "Leverage": cfg["name"],
                    "Event": event_name,
                    "Strategy Decline": strat_decline,
                    "VIX-Adaptive Decline": vix_decline,
                    "Buy & Hold Decline": bh_decline,
                    # Both declines are negative numbers; VIX-adaptive doing better than
                    # baseline means vix_decline is LESS negative, so vix - strat > 0.
                    "VIX Improvement (pp)": vix_decline - strat_decline,  # positive = VIX-adaptive helped
                })

    df = pd.DataFrame(rows)

    lines = [f"### Event-Relative Decline: Strategy vs VIX-Adaptive (VIX>{VIX_BYPASS_THRESHOLD} bypass) vs Buy & Hold", "",
             "| Ticker | Leverage | Event | Strategy Decline | VIX-Adaptive Decline | Buy & Hold Decline | VIX Improvement (pp) |",
             "| :--- | :--- | :--- | ---: | ---: | ---: | ---: |"]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['Ticker']} | {r['Leverage']} | {r['Event']} | {r['Strategy Decline']:.2f}% "
            f"| {r['VIX-Adaptive Decline']:.2f}% | {r['Buy & Hold Decline']:.2f}% | {r['VIX Improvement (pp)']:+.2f} |"
        )
    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
