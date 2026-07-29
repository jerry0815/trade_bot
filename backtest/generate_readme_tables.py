"""
Regenerates the three rolling-backtest performance tables shown in README.md.

Run manually after any change to strategy logic (e.g. t2_confirmation) that
should be reflected in the published results:

    python backtest/generate_readme_tables.py

Writes markdown table rows to stdout AND backtest/readme_tables_output.md.
Copy the relevant rows into README.md by hand — this keeps the prose
(commentary, "vs Table 1" analysis) under human editorial control while
guaranteeing the numbers are exactly what the current strategy produces.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # allow running as `python backtest/generate_readme_tables.py` from anywhere
from backtest.strat_backtest import (
    BuyAndHold, SMATrendFollowing, VolatilityFilter, EMACrossover, RSIMeanReversion,
    run_experiment_suite, warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "readme_tables_output.md"

PERIOD_YEARS = 26
LEVERAGE_CONFIGS = [
    {"name": "3x", "leverage": 3, "expense": 0.0095},
    {"name": "2x", "leverage": 2, "expense": 0.0095},
    {"name": "1x", "leverage": 1, "expense": 0.0020},
]


def build_strategies():
    # Fresh instances per call — strategies carry no mutable run state, but
    # keeping construction local avoids any accidental cross-table sharing.
    #
    # NOTE on display names: the raw strategy name printed here (e.g.
    # "SMA 200 - ATR Buffer (x2.5) [T+2]") is intentionally transcribed to a
    # shorter display name by hand when copying rows into README.md (e.g.
    # "SMA 200 (ATR x2.5, T+2)"). This script does not attempt to rename the
    # strategies themselves — that's out of scope for table generation.
    return [
        BuyAndHold(),
        SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True),
        EMACrossover(name="EMA 50/200"),
        VolatilityFilter(name="VIX < 25", vix_threshold=25),
        RSIMeanReversion(name="RSI 30/70"),
    ]


def render_markdown_table(title, date_range_note, leverage_to_rows):
    lines = [f"### {title}", f"*{date_range_note}*", "",
             "| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |",
             "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for lev_name, rows in leverage_to_rows.items():
        for r in rows:
            lines.append(
                f"| **{lev_name}** | {r['Strategy']} | {r['Avg TWR']:.2f}% | {r['Med TWR']:.2f}% "
                f"| {r['Worst TWR']:.2f}% | {r['Worst DD']:.2f}% | {r['Avg Trades']:.0f} |"
            )
        lines.append("| | | | | | | |")
    return "\n".join(lines)


def run_table(title, base_ticker, signal_ticker=None):
    # Warmup needs data from every ticker actually used by this table — for
    # cross-signal tables (Table 3) that means both the base and signal
    # ticker, since the window can't start until both have data available.
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
        leverage_to_rows[cfg["name"]] = summarize_rolling_results(df_res, strategies)
        # Visibility: RollingBacktester.run() silently drops rejected windows
        # (e.g. insufficient data span). Report acceptance rate so a large
        # rejection rate is obvious immediately rather than discovered later
        # by manually diffing date strings.
        print(f"  {cfg['name']}: {len(df_res)}/{len(start_dates)} candidate windows accepted")
        if not df_res.empty:
            n_windows = len(df_res)
            date_lo, date_hi = df_res["Start Date"].min(), df_res["Start Date"].max()
    if date_lo is None or date_hi is None:
        note = "Date range: NO WINDOWS ACCEPTED for any leverage tier — check ticker data availability."
    else:
        note = f"Date range: {date_lo.date()} to {date_hi.date()} ({n_windows} rolling windows)"
    return render_markdown_table(title, note, leverage_to_rows)


if __name__ == "__main__":
    out = []
    print("Running Table 1: NASDAQ-100 (^NDX)...")
    out.append(run_table("Table 1: NASDAQ-100 (^NDX) — Lump Sum Performance", "^NDX"))

    print("Running Table 2: S&P 500 (^GSPC)...")
    out.append(run_table("Table 2: S&P 500 (^GSPC) — Lump Sum Performance", "^GSPC"))

    print("Running Table 3: NDX returns + GSPC signal...")
    out.append(run_table(
        "Table 3: NASDAQ-100 Returns + S&P 500 Signal — Lump Sum Performance",
        "^NDX", signal_ticker="^GSPC",
    ))

    full_output = "\n\n---\n\n".join(out)
    print("\n" + full_output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"\nWritten to {OUTPUT_PATH}")
