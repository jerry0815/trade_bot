"""
Full comparison of four configurations, on both the 172-window rolling
aggregate (in-sample) and the 2016-01-01-to-today held-out period
(out-of-sample), pre-tax, ^NDX/3x:

  A  SMA 200 + T+2, S&P 500 signal          -- the live bot.py baseline
  B  A + GSPC trailing stop (8%, 60d)       -- the published stop candidate
  C  Dual-signal agreement, no T+2          -- current README Table 4 pick
  D  C + GSPC trailing stop (8%, 60d)       -- the combined system

Answers two things at once:
1. Does dual-signal's in-sample return edge over SMA+T+2 survive on the
   untouched 2016-today period? (README Table 4 explicitly never checked
   this.) Compare rows A vs C across the two tables.
2. What does adding the GSPC trailing stop do to each base strategy, in and
   out of sample? Compare A->B and C->D.

Honesty note on the OOS split: the 172 rolling windows (starts 1986-2000,
26-year spans) DO extend past 2016, so the 2016-today evaluation is not a
perfectly leak-free split for these fixed strategies -- but neither strategy
has a tuned parameter being selected on the rolling set, so the overfitting
risk the calendar-cutoff design was built for is low here. Read the OOS
table as a regime-change robustness check (COVID + 2022, events the
strategies were not designed around) rather than a pristine hold-out.

Reuses SMATrendFollowing, and DualSignalSingleStop from
trailing_stop_dual_breach.py (dual-signal entry + reused single-ticker
GSPC stop overlay). No engine changes.

Run manually:
    python backtest/combined_system_comparison.py
"""
import sys
import warnings
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, Backtester, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)
from backtest.trailing_stop_dual_breach import DualSignalSingleStop

OUTPUT_PATH = REPO_ROOT / "backtest" / "combined_system_comparison_output.md"

CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26
ATR = 2.5
STOP_PCT = 0.08
STOP_COOLDOWN = 60
CUTOFF = pd.Timestamp("2016-01-01")


def make_configs():
    """Returns [(key, label, strategy, signal_ticker, base_pair_key)].
    base_pair_key names the no-stop counterpart for per-window DD win rate."""
    A = SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True)
    B = SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True,
                          trailing_stop_pct=STOP_PCT, trailing_stop_cooldown_days=STOP_COOLDOWN)
    C = DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False)
    D = DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False, tag="GSPC",
                             trailing_stop_pct=STOP_PCT, trailing_stop_cooldown_days=STOP_COOLDOWN)
    # All run with the S&P 500 signal ticker: A/B use it as the SMA signal;
    # C/D compute the dual signal internally but it fixes df['Close']=^GSPC,
    # so D's stop tracks ^GSPC. One window set for all four.
    return [
        ("A", "SMA+T+2 (baseline)", A, "^GSPC", None),
        ("B", "SMA+T+2 + GSPC stop 8/60", B, "^GSPC", "A"),
        ("C", "Dual-signal (no T+2)", C, "^GSPC", None),
        ("D", "Dual-signal + GSPC stop 8/60", D, "^GSPC", "C"),
    ]


def rolling_table(configs):
    strategies = [c[2] for c in configs]
    start_dates = warmup_aware_start_dates(["^NDX", "^GSPC"], PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker="^NDX", signal_ticker="^GSPC",
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)
    by_key = {c[0]: (c, s) for c, s in zip(configs, summary)}

    lines = [f"### In-Sample: 172-Window Rolling Aggregate (^NDX/3x, S&P signal, pre-tax)", "",
             "| Cfg | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Mean Max DD | DD improved vs pair | Trades |",
             "| :-- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for (key, label, strat, _sig, pair), s in zip(configs, summary):
        col = f"{strat.name} Max DD (%)"
        if pair is None:
            dd_win = "--"
        else:
            pair_strat = by_key[pair][0][2]
            pcol = f"{pair_strat.name} Max DD (%)"
            better = int((df_res[col] > df_res[pcol]).sum())
            dd_win = f"{better}/172 (vs {pair})"
        lines.append(
            f"| {key} | {label} | {s['Avg TWR']:.2f}% | {s['Med TWR']:.2f}% | {s['Worst TWR']:.2f}% "
            f"| {s['Worst DD']:.2f}% | {df_res[col].mean():.2f}% | {dd_win} | {s['Avg Trades']:.1f} |"
        )
    return "\n".join(lines)


def oos_table(configs):
    period_years = int((pd.Timestamp.today() - CUTOFF).days / 365.25)
    lines = [f"### Out-of-Sample: Single Backtest {CUTOFF.date()} to today ({period_years}y, ^NDX/3x, pre-tax)", "",
             "| Cfg | Strategy | TWR | Max DD | Trades |",
             "| :-- | :--- | ---: | ---: | ---: |"]
    for key, label, strat, sig, _pair in configs:
        env = Backtester(
            base_ticker="^NDX", signal_ticker=sig,
            start_date=CUTOFF.strftime("%Y-%m-%d"), period_years=period_years,
            leverage=CONFIG["leverage"], expense_ratio=CONFIG["expense"],
            initial_fund=10000, apply_tax=False, verbose=False,
        )
        res = env.run(strat)
        if res is None:
            lines.append(f"| {key} | {label} | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| {key} | {label} | {res['strategy_twr']:.2f}% | {res['max_drawdown']:.2f}% "
            f"| {len(res['trade_log'])} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    configs = make_configs()

    print("Running 172-window rolling aggregate for 4 configs...")
    roll = rolling_table(configs)
    print("Running 2016-today out-of-sample single backtests for 4 configs...")
    oos = oos_table(configs)

    note = "\n".join([
        "**How to read this:**",
        "- A vs C: does dual-signal's in-sample return edge (Table 1) survive",
        "  out-of-sample? (README Table 4 never checked this.)",
        "- A->B and C->D: what the GSPC trailing stop does to each base, in and",
        "  out of sample. The stop is a drawdown tool; watch Max DD vs TWR.",
        "- The 172 rolling windows overlap the 2016-today period, so the OOS",
        "  table is a regime-change robustness check, not a pristine hold-out",
        "  (neither strategy tunes a parameter on the rolling set, so this is",
        "  acceptable -- see script header).",
    ])
    output = "\n\n".join([roll, oos, note])
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
