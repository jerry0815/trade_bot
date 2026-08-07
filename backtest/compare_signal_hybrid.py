"""
Quick comparison: NDX-own signal vs S&P 500 signal vs a dual-signal
"agreement" hybrid (only flips state when both ^NDX and ^GSPC's SMA+ATR
trend signals agree), each with T+2 confirmation off and on.

Fixed at ATR x2.5 (bot.py's current default) and 3x leverage — this is a
targeted follow-up question, not a parameter sweep, so it doesn't vary ATR.

Run manually:
    python backtest/compare_signal_hybrid.py

Writes a markdown table to stdout AND backtest/signal_hybrid_output.md.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, DualSignalAgreement, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "signal_hybrid_output.md"

PERIOD_YEARS = 26
LEVERAGE_CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR = 2.5

SETUPS = [
    ("NDX own signal", SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=False), None),
    ("NDX own signal [T+2]", SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True), None),
    ("S&P 500 signal", SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=False), "^GSPC"),
    ("S&P 500 signal [T+2]", SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True), "^GSPC"),
    ("Dual-signal agreement", DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False), None),
    ("Dual-signal agreement [T+2]", DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=True), None),
    # Trailing-stop overlays (opt-in ^GSPC stop, 8% / 60d cooldown). The stop
    # tracks ^GSPC in both: for the S&P setup df['Close'] is ^GSPC; for the
    # dual-signal setup DualSignalAgreement fetches ^GSPC internally.
    ("S&P 500 signal [T+2] + Trailing Stop 8%/60d",
     SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True,
                       trailing_stop_pct=0.08, trailing_stop_cooldown_days=60), "^GSPC"),
    ("Dual-signal agreement + Trailing Stop 8%/60d",
     DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False,
                         trailing_stop_pct=0.08, trailing_stop_cooldown_days=60), None),
]


def run_setup(label, strat, signal_ticker):
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    if isinstance(strat, DualSignalAgreement):
        tickers = ["^NDX", "^GSPC"]  # needs both regardless of signal_ticker
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[LEVERAGE_CONFIG],
        strategies=[strat],
        start_dates=start_dates,
        period_years=PERIOD_YEARS,
        annual_dca=0,
        base_ticker="^NDX",
        signal_ticker=signal_ticker,
        initial_fund=10000,
        apply_tax=False,
        print_summary=False,
    )
    df_res = results[LEVERAGE_CONFIG["name"]]
    print(f"  {label}: {len(df_res)}/{len(start_dates)} candidate windows accepted")
    summary = summarize_rolling_results(df_res, [strat], metric_label="TWR")
    if not summary:
        return None
    row = dict(summary[0])
    row["Label"] = label
    row["n_windows"] = len(df_res)
    date_lo, date_hi = (df_res["Start Date"].min(), df_res["Start Date"].max()) if not df_res.empty else (None, None)
    row["date_range"] = f"{date_lo.date()} to {date_hi.date()}" if date_lo is not None else "N/A"
    return row


if __name__ == "__main__":
    rows = []
    for label, strat, signal_ticker in SETUPS:
        row = run_setup(label, strat, signal_ticker)
        if row:
            rows.append(row)

    lines = [
        "### NDX Signal vs S&P 500 Signal vs Dual-Signal Agreement (ATR x2.5, 3x Leverage)",
        "",
        "| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Worst DD vs Init | Avg Trades | Windows |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['Label']} | {r['Avg TWR']:.2f}% | {r['Med TWR']:.2f}% | {r['Worst TWR']:.2f}% "
            f"| {r['Worst DD']:.2f}% | {r['Worst DD vs Initial']:.2f}% | {r['Avg Trades']:.0f} "
            f"| {r['n_windows']} ({r['date_range']}) |"
        )
    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
