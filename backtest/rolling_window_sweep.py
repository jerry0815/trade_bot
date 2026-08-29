"""Rolling-window sweep of the production configs at one or more window
lengths, reporting the full return distribution *with Sharpe* plus a 1x
buy-and-hold index baseline.

Motivation: the core RollingBacktester (strat_backtest.RollingBacktester)
reports the TWR/drawdown distribution but drops each window's equity curve,
so it can't emit Sharpe (see README note). This driver instead runs
`Backtester` directly per window, keeping each window's equity_curve, and
computes per-window Sharpe with the repo's canonical `sharpe_from_equity`.

It reuses the EXACT four production configs (A-D) from
combined_system_comparison.make_configs() -- D is the recommended combined
system (dual-signal + GSPC 8%/60d trailing stop) -- and adds:

  BH  Buy & Hold, unleveraged ^NDX index (leverage=1, 0% fee)

as a fifth baseline row.

Generates the README's "Shorter-horizon view" table. Run:

    python backtest/rolling_window_sweep.py                # 10-year windows
    python backtest/rolling_window_sweep.py --years 10 26  # side-by-side
"""
import argparse
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    Backtester, BuyAndHold, warmup_aware_start_dates, get_cached_signals,
)
from backtest.combined_system_comparison import make_configs, CONFIG
from backtest.dynamic_leverage_screen import sharpe_from_equity

OUTPUT_PATH = REPO_ROOT / "backtest" / "rolling_window_sweep_output.md"

# The 1x index baseline is always-in-market ^NDX at unit leverage, 0% fee.
BH_KEY = "BH"
BH_LABEL = "Buy & Hold ^NDX 1x (index)"


def run_window_length(years, workers=8):
    """Run all configs + the 1x baseline over `years`-length rolling windows.

    Returns (start_dates, accepted_df). accepted_df has MultiIndex-tuple
    columns (cfg_key, metric) for metric in {twr, dd, sharpe, trades}.
    """
    configs = make_configs()  # (key, label, strat, signal_ticker, pair)
    bh = BuyAndHold()
    start_dates = warmup_aware_start_dates(["^NDX", "^GSPC"], years)

    # Pre-warm caches single-threaded so worker threads only read.
    get_cached_signals("^GSPC")
    get_cached_signals("^NDX")

    def run_one(start_date):
        date_str = start_date.strftime("%Y-%m-%d")
        env = Backtester(
            base_ticker="^NDX", signal_ticker="^GSPC", start_date=date_str,
            period_years=years, leverage=CONFIG["leverage"],
            expense_ratio=CONFIG["expense"], initial_fund=10000,
            apply_tax=False, verbose=False,
        )
        row = {}
        for key, _label, strat, _sig, _pair in configs:
            res = env.run(strat)
            if res is None:
                return None  # window lacks full data for a config -> drop it
            row[(key, "twr")] = res["strategy_twr"]
            row[(key, "dd")] = res["max_drawdown"]
            row[(key, "sharpe")] = sharpe_from_equity(res["equity_curve"])
            row[(key, "trades")] = len(res["trade_log"])
        # 1x buy-and-hold baseline: unleveraged ^NDX, always in, 0% fee.
        bh_env = Backtester(
            base_ticker="^NDX", signal_ticker="^NDX", start_date=date_str,
            period_years=years, leverage=1, expense_ratio=0.0,
            initial_fund=10000, apply_tax=False, verbose=False,
        )
        bh_res = bh_env.run(bh)
        if bh_res is None:
            return None
        row[(BH_KEY, "twr")] = bh_res["strategy_twr"]
        row[(BH_KEY, "dd")] = bh_res["max_drawdown"]
        row[(BH_KEY, "sharpe")] = sharpe_from_equity(bh_res["equity_curve"])
        row[(BH_KEY, "trades")] = 0
        return row

    with ThreadPoolExecutor(max_workers=min(workers, len(start_dates))) as pool:
        rows = [r for r in pool.map(run_one, start_dates) if r is not None]
    return start_dates, pd.DataFrame(rows)


def render_table(years, start_dates, df):
    """Render the README-shaped markdown table for one window length."""
    configs = make_configs()
    rows = [(k, lbl) for k, lbl, *_ in configs] + [(BH_KEY, BH_LABEL)]

    header = (
        f"#### {years}-Year Rolling Windows "
        f"({len(df)} windows, {start_dates[0].date()}–{start_dates[-1].date()} starts)\n\n"
        "| Cfg | Strategy | Avg CAGR | Med CAGR | Worst-window CAGR | % windows <0 "
        "| Avg Sharpe | Mean maxDD | Worst DD |\n"
        "| :-- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    lines = [header]
    for key, label in rows:
        twr, shrp, dd = df[(key, "twr")], df[(key, "sharpe")], df[(key, "dd")]
        emph = "**" if key == "D" else ""
        name = f"{label} (recommended)" if key == "D" else label
        lines.append(
            f"| {emph}{key}{emph} | {emph}{name}{emph} "
            f"| {emph}{twr.mean():.1f}%{emph} | {twr.median():.1f}% "
            f"| {emph}{twr.min():.1f}%{emph} | {emph}{(twr < 0).mean() * 100:.1f}%{emph} "
            f"| {emph}{shrp.mean():.2f}{emph} | {dd.mean():.1f}% | {emph}{dd.min():.1f}%{emph} |"
        )
    return "\n".join(lines)


NOTES = (
    "*Rolling windows step monthly (overlapping), next-day-open execution, "
    "pre-tax, cash when out of market. A–D are 3× ^NDX (TQQQ exposure); BH is "
    "the unleveraged NASDAQ-100 index at 0% fee. Sharpe is annualized on daily "
    "returns at rf = 0 (252-day convention). Overlapping windows share most of "
    "their data, so this distribution understates true sampling variance.*\n\n"
    "- **% windows <0** — share of rolling windows whose *annualized return* came "
    "out negative (a losing hold over that horizon); measures how *often* a bad "
    "window happened, not how deep (see the drawdown columns).\n"
    "- **GSPC stop 8%/60d** — crash-protection trailing stop on the unleveraged "
    "S&P 500 (`^GSPC`): exit the day it closes 8% below its since-entry peak, then "
    "a 60-trading-day re-entry cooldown. Configs B and D use it; A and C do not."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--years", type=int, nargs="+", default=[10],
        help="One or more rolling-window lengths in years (default: 10).",
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    warnings.filterwarnings("ignore")

    tables = []
    for years in args.years:
        print(f"Running {years}-year rolling sweep (5 configs incl. 1x baseline)...")
        start_dates, df = run_window_length(years, workers=args.workers)
        print(f"  accepted windows (full data): {len(df)} / {len(start_dates)}")
        tables.append(render_table(years, start_dates, df))

    output = "\n\n".join(tables) + "\n\n" + NOTES
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output + "\n")
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
