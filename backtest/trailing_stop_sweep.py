"""
Sweeps trailing_stop_pct x trailing_stop_cooldown_days for SMATrendFollowing
against the live bot.py config (S&P-signal-driven, ^NDX/3x), reporting
event-relative decline for all 5 known crises per combination. Same
event-relative methodology as backtest/event_leverage_comparison.py: each
event's decline is measured from the equity value at/just-before the
event's well-known start date to the local trough within the event window,
independent of whether an earlier, still-unresolved drawdown was already
in progress.

Run manually:
    python backtest/trailing_stop_sweep.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing, Backtester

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_sweep_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
LEVERAGE = 3
EXPENSE = 0.0095

# Corrected grid (see docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md
# Component 2 addendum): measured against the underlying signal-ticker price,
# the dot-com trade's peak-to-trough was only ~-13%, so the real effect lives
# in the 5-20% range, not the original 10-30% estimate (which was based on
# the leveraged equity curve).
PCT_GRID = [0.05, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20]
COOLDOWN_GRID = [10, 20, 40, 60]

EVENTS = [
    ("Black Monday 1987",    "1987-08-25", "1987-12-04"),
    ("Dot-com crash",        "2000-03-24", "2002-10-09"),
    ("2008 GFC",             "2007-10-09", "2009-03-09"),
    ("COVID crash",          "2020-02-19", "2020-03-23"),
    ("2022 rate-shock bear", "2022-01-03", "2022-10-12"),
]


def get_equity_curve(strategy):
    env = Backtester(
        base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER, start_date="1986-04-29",
        period_years=40, leverage=LEVERAGE, expense_ratio=EXPENSE,
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


if __name__ == "__main__":
    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    eq_baseline = get_equity_curve(baseline)

    rows = []
    for pct in PCT_GRID:
        for cooldown in COOLDOWN_GRID:
            strat = SMATrendFollowing(
                sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                trailing_stop_pct=pct, trailing_stop_cooldown_days=cooldown,
            )
            print(f"Running pct={pct:.0%} cooldown={cooldown}d...")
            eq_strat = get_equity_curve(strat)
            if eq_strat is None:
                continue
            for event_name, start, end in EVENTS:
                base_decline = event_decline(eq_baseline, start, end)
                stop_decline = event_decline(eq_strat, start, end)
                if base_decline is None or stop_decline is None:
                    continue
                rows.append({
                    "Pct": pct,
                    "Cooldown": cooldown,
                    "Event": event_name,
                    "Baseline Decline": base_decline,
                    "Stop Decline": stop_decline,
                    # Both declines are negative numbers; the stop doing
                    # better means stop_decline is LESS negative, so
                    # stop - baseline > 0 means improvement.
                    "Improvement (pp)": stop_decline - base_decline,
                })

    df = pd.DataFrame(rows)
    lines = ["### Trailing-Stop Sweep: Event-Relative Decline vs Baseline (^NDX/3x, S&P signal)", "",
             "| Pct | Cooldown | Event | Baseline Decline | Stop Decline | Improvement (pp) |",
             "| ---: | ---: | :--- | ---: | ---: | ---: |"]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['Pct']:.0%} | {r['Cooldown']:.0f}d | {r['Event']} | {r['Baseline Decline']:.2f}% "
            f"| {r['Stop Decline']:.2f}% | {r['Improvement (pp)']:+.2f} |"
        )
    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
