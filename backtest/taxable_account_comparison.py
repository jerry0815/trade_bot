"""
Taxable-account (after-tax) comparison for the four "key" ^NDX/3x/ATR2.5
setups: S&P-signal [T+2] (with and without the 8%/60d peak trailing stop)
and dual-signal agreement (with and without the same stop).

For each setup, runs the 26-yr monthly rolling suite TWICE via
run_experiment_suite() -- once apply_tax=False, once apply_tax=True -- and
reports the full rolling distribution: Pre-Tax Avg TWR, After-Tax Avg / Med
/ Worst TWR (across all rolling windows), Tax Drag (pp) = pre-avg - after-avg,
After-Tax Worst DD, and Avg Trades. Reporting the median and worst-case
after-tax return (not just the average) makes this a proper rolling-test
view, consistent with Tables 1-4. This surfaces the point that the
trailing-stop variants trade more often, realizing more short-term gains,
so they should show a *larger* tax drag than their no-stop counterparts
even though their pre-tax edge looked attractive.

Tax rates are the Backtester's built-in defaults (not varied here):
TAX_SHORT_TERM_RATE = 25% (gains on trades held <= 365 days)
TAX_LONG_TERM_RATE  = 15% (gains on trades held > 365 days)
See strat_backtest.py.

Run manually:
    python backtest/taxable_account_comparison.py

Writes a markdown table to stdout AND
backtest/taxable_account_comparison_output.md.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, DualSignalAgreement, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "taxable_account_comparison_output.md"

PERIOD_YEARS = 26
LEVERAGE_CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR = 2.5
STOP_PCT = 0.08
STOP_COOLDOWN = 60

SETUPS = [
    ("S&P-signal [T+2]",
     lambda: SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True),
     "^GSPC"),
    ("S&P-signal [T+2] + peak stop 8/60",
     lambda: SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True,
                               trailing_stop_pct=STOP_PCT, trailing_stop_cooldown_days=STOP_COOLDOWN),
     "^GSPC"),
    ("Dual-signal",
     lambda: DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False),
     None),
    ("Dual-signal + peak stop 8/60",
     lambda: DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False,
                                 trailing_stop_pct=STOP_PCT, trailing_stop_cooldown_days=STOP_COOLDOWN),
     None),
]


def run_setup(label, strat_factory, signal_ticker):
    """Runs the rolling suite twice (apply_tax=False, then True) for one
    setup and returns a combined pre/after-tax summary row."""
    probe = strat_factory()
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    if isinstance(probe, DualSignalAgreement):
        tickers = ["^NDX", "^GSPC"]  # needs both regardless of signal_ticker
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)

    def _run(apply_tax):
        strat = strat_factory()
        results = run_experiment_suite(
            configs=[LEVERAGE_CONFIG],
            strategies=[strat],
            start_dates=start_dates,
            period_years=PERIOD_YEARS,
            annual_dca=0,
            base_ticker="^NDX",
            signal_ticker=signal_ticker,
            initial_fund=10000,
            apply_tax=apply_tax,
            print_summary=False,
        )
        df_res = results[LEVERAGE_CONFIG["name"]]
        summary = summarize_rolling_results(df_res, [strat], metric_label="TWR")
        return df_res, (summary[0] if summary else None)

    pretax_df, pretax_row = _run(False)
    aftertax_df, aftertax_row = _run(True)

    print(f"  {label}: pre-tax {len(pretax_df)}/{len(start_dates)}, "
          f"after-tax {len(aftertax_df)}/{len(start_dates)} candidate windows accepted")

    if pretax_row is None or aftertax_row is None:
        return None

    date_lo, date_hi = (aftertax_df["Start Date"].min(), aftertax_df["Start Date"].max()) \
        if not aftertax_df.empty else (None, None)
    date_range = f"{date_lo.date()} to {date_hi.date()}" if date_lo is not None else "N/A"

    return {
        "Label": label,
        "Pre-Tax Avg TWR": pretax_row["Avg TWR"],
        "After-Tax Avg TWR": aftertax_row["Avg TWR"],
        "After-Tax Med TWR": aftertax_row["Med TWR"],
        "After-Tax Worst TWR": aftertax_row["Worst TWR"],
        "Tax Drag": pretax_row["Avg TWR"] - aftertax_row["Avg TWR"],
        "After-Tax Worst DD": aftertax_row["Worst DD"],
        "After-Tax Worst DD vs Initial": aftertax_row["Worst DD vs Initial"],
        "Avg Trades": aftertax_row["Avg Trades"],
        "n_windows": len(aftertax_df),
        "date_range": date_range,
    }


if __name__ == "__main__":
    rows = []
    for label, strat_factory, signal_ticker in SETUPS:
        row = run_setup(label, strat_factory, signal_ticker)
        if row:
            rows.append(row)

    lines = [
        "### Taxable Account — Pre-Tax vs After-Tax Rolling Comparison "
        "(^NDX/3x, ATR x2.5, 26yr rolling windows, 25%/15% rates)",
        "",
        "| Setup | Pre-Tax Avg TWR | After-Tax Avg TWR | After-Tax Med TWR "
        "| After-Tax Worst TWR | Tax Drag (pp) | After-Tax Worst DD "
        "| After-Tax Worst DD vs Init | Avg Trades | Windows |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['Label']} | {r['Pre-Tax Avg TWR']:.2f}% | {r['After-Tax Avg TWR']:.2f}% "
            f"| {r['After-Tax Med TWR']:.2f}% | {r['After-Tax Worst TWR']:.2f}% "
            f"| {r['Tax Drag']:+.2f} | {r['After-Tax Worst DD']:.2f}% "
            f"| {r['After-Tax Worst DD vs Initial']:.2f}% | {r['Avg Trades']:.0f} "
            f"| {r['n_windows']} ({r['date_range']}) |"
        )
    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
