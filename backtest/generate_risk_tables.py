"""
Risk-adjusted companion to generate_readme_tables.py.

Runs the exact same rolling-backtest configs that produce README Tables 1-3
(same tickers, leverage tiers, strategies, 26-year monthly windows) but
reports Sharpe / Sortino / Calmar instead of raw TWR. Each ratio is computed
*within* every rolling window by the engine, then aggregated across windows
(median = robust central tendency; mean = shown alongside for skew).

    python backtest/generate_risk_tables.py

Prints per-leverage, per-strategy ratio tables to stdout and writes them to
backtest/risk_tables_output.md.
"""
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    BuyAndHold, SMATrendFollowing, VolatilityFilter, EMACrossover, RSIMeanReversion,
    run_experiment_suite, warmup_aware_start_dates,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "risk_tables_output.md"

PERIOD_YEARS = 26
LEVERAGE_CONFIGS = [
    {"name": "3x", "leverage": 3, "expense": 0.0095},
    {"name": "2x", "leverage": 2, "expense": 0.0095},
    {"name": "1x", "leverage": 1, "expense": 0.0020},
]

# Shorter display names, matching how README transcribes the raw strategy names.
DISPLAY_NAMES = {
    "Buy & Hold": "Buy & Hold",
    "SMA 200 - ATR Buffer (x2.5) [T+2]": "SMA 200 (ATR x2.5, T+2)",
    "EMA 50/200": "EMA 50/200",
    "VIX < 25": "VIX < 25",
    "RSI 30/70": "RSI 30/70",
}


def build_strategies():
    return [
        BuyAndHold(),
        SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True),
        EMACrossover(name="EMA 50/200"),
        VolatilityFilter(name="VIX < 25", vix_threshold=25),
        RSIMeanReversion(name="RSI 30/70"),
    ]


def summarize_risk_results(df_res, strategies):
    """Aggregate each strategy's per-window Sharpe/Sortino/Calmar across all
    windows. Uses nan-aware mean/median so a rare degenerate window (e.g. a
    zero-downside Sortino) doesn't poison the whole column."""
    rows = []
    for strat in strategies:
        cols = {m: f"{strat.name} {m}" for m in ("Sharpe", "Sortino", "Calmar")}
        if cols["Sharpe"] not in df_res.columns:
            continue
        row = {"Strategy": DISPLAY_NAMES.get(strat.name, strat.name)}
        for metric, col in cols.items():
            vals = df_res[col].to_numpy(dtype=float)
            row[f"Med {metric}"] = np.nanmedian(vals)
            row[f"Avg {metric}"] = np.nanmean(vals)
        rows.append(row)
    return rows


def render_markdown_table(title, date_range_note, leverage_to_rows):
    lines = [f"### {title}", f"*{date_range_note}*", "",
             "| Leverage | Strategy | Med Sharpe | Med Sortino | Med Calmar | Avg Sharpe | Avg Sortino | Avg Calmar |",
             "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for lev_name, rows in leverage_to_rows.items():
        for r in rows:
            lines.append(
                f"| **{lev_name}** | {r['Strategy']} "
                f"| {r['Med Sharpe']:.2f} | {r['Med Sortino']:.2f} | {r['Med Calmar']:.2f} "
                f"| {r['Avg Sharpe']:.2f} | {r['Avg Sortino']:.2f} | {r['Avg Calmar']:.2f} |"
            )
        lines.append("| | | | | | | | |")
    return "\n".join(lines)


def run_table(title, base_ticker, signal_ticker=None):
    tickers = [base_ticker] if signal_ticker is None else [base_ticker, signal_ticker]
    strategies = build_strategies()
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=LEVERAGE_CONFIGS,
        strategies=strategies,
        start_dates=start_dates,
        period_years=PERIOD_YEARS,
        annual_dca=0,
        base_ticker=base_ticker,
        signal_ticker=signal_ticker,
        initial_fund=10000,
        apply_tax=False,
        print_summary=False,
    )
    leverage_to_rows = {}
    n_windows = None
    date_lo = date_hi = None
    for cfg in LEVERAGE_CONFIGS:
        df_res = results[cfg["name"]]
        leverage_to_rows[cfg["name"]] = summarize_risk_results(df_res, strategies)
        print(f"  {cfg['name']}: {len(df_res)}/{len(start_dates)} candidate windows accepted")
        if not df_res.empty:
            n_windows = len(df_res)
            date_lo, date_hi = df_res["Start Date"].min(), df_res["Start Date"].max()
    if date_lo is None or date_hi is None:
        note = "Date range: NO WINDOWS ACCEPTED — check ticker data availability."
    else:
        note = f"Date range: {date_lo.date()} to {date_hi.date()} ({n_windows} rolling windows)"
    return render_markdown_table(title, note, leverage_to_rows)


if __name__ == "__main__":
    out = []
    print("Running Table 1 (risk): NASDAQ-100 (^NDX)...")
    out.append(run_table("Table 1R: NASDAQ-100 (^NDX) — Risk-Adjusted Ratios", "^NDX"))

    print("Running Table 2 (risk): S&P 500 (^GSPC)...")
    out.append(run_table("Table 2R: S&P 500 (^GSPC) — Risk-Adjusted Ratios", "^GSPC"))

    print("Running Table 3 (risk): NDX returns + GSPC signal...")
    out.append(run_table(
        "Table 3R: NASDAQ-100 Returns + S&P 500 Signal — Risk-Adjusted Ratios",
        "^NDX", signal_ticker="^GSPC",
    ))

    full_output = "\n\n---\n\n".join(out)
    print("\n" + full_output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"\nWritten to {OUTPUT_PATH}")
