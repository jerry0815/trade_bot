"""
Generates README's Table 4: a 3x-leverage ^NDX (TQQQ) comparison of SMA
and EMA across ATR multiplier, signal source, and T+2 confirmation.

Run manually:
    python backtest/generate_signal_comparison.py

Writes the computed "best real-world practice" pick plus two markdown
tables (SMA sweep, EMA sweep) to stdout AND
backtest/signal_comparison_output.md. Copy the relevant content into
README.md by hand — same generate-then-hand-transcribe pattern as
generate_readme_tables.py.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, EMACrossover, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "signal_comparison_output.md"

PERIOD_YEARS = 26
LEVERAGE_CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR_VALUES = [1.5, 2.0, 2.5, 3.0, 3.5]
SIGNAL_SOURCES = [("Own (^NDX)", None), ("S&P 500 (^GSPC)", "^GSPC")]
T2_STATES = [("Off", False), ("On", True)]


def build_sma_variants():
    variants = []
    for atr in ATR_VALUES:
        for signal_label, signal_ticker in SIGNAL_SOURCES:
            for t2_label, t2 in T2_STATES:
                strat = SMATrendFollowing(sma_window=200, atr_multiplier=atr, t2_confirmation=t2)
                variants.append({
                    "strategy": strat,
                    "signal_ticker": signal_ticker,
                    "row": {"ATR": f"x{atr}", "Signal": signal_label, "T+2": t2_label},
                })
    return variants


def build_ema_variants():
    variants = []
    for atr in [None] + ATR_VALUES:
        for signal_label, signal_ticker in SIGNAL_SOURCES:
            for t2_label, t2 in T2_STATES:
                strat = EMACrossover(atr_multiplier=atr, t2_confirmation=t2)
                variants.append({
                    "strategy": strat,
                    "signal_ticker": signal_ticker,
                    "row": {"ATR": f"x{atr}" if atr else "None", "Signal": signal_label, "T+2": t2_label},
                })
    return variants


def run_variant(variant, start_dates=None):
    strat = variant["strategy"]
    signal_ticker = variant["signal_ticker"]
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    if start_dates is None:
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
    # Visibility: RollingBacktester.run() silently drops rejected windows (e.g.
    # insufficient data span). Report acceptance vs. candidate count per variant
    # so a variant-specific rejection is obvious immediately rather than only
    # discovered later by manually diffing window counts — mirrors the print
    # already used in generate_readme_tables.py's run_table().
    print(f"    {len(df_res)}/{len(start_dates)} candidate windows accepted")
    summary = summarize_rolling_results(df_res, [strat], metric_label="TWR")
    if not summary:
        return None
    row = dict(variant["row"])
    row.update(summary[0])
    row["n_windows"] = len(df_res)
    return row


def render_table(title, rows):
    rows_sorted = sorted(rows, key=lambda r: r["Avg TWR"], reverse=True)
    lines = [f"### {title}", "",
             "| ATR | Signal | T+2 | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |",
             "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows_sorted:
        lines.append(
            f"| {r['ATR']} | {r['Signal']} | {r['T+2']} | {r['Avg TWR']:.2f}% | {r['Med TWR']:.2f}% "
            f"| {r['Worst TWR']:.2f}% | {r['Worst DD']:.2f}% | {r['Avg Trades']:.0f} |"
        )
    return "\n".join(lines)


def pick_best_practice(all_rows):
    """Mechanically pick the highest-Avg-TWR row after excluding the worst
    quartile by Worst DD (deepest/most negative drawdown first).

    Tie-break note: `sorted()` is stable, so rows with equal Worst DD keep
    their original `all_rows` relative order in `ranked_by_dd` — a tie that
    straddles the quartile boundary is broken by insertion order, not by any
    secondary metric. (In the current 44-row dataset, real Worst-DD ties do
    exist — e.g. -96.26% and -83.40% each appear twice — but none land
    exactly on the 11/12 cut, so this tie-break rule isn't actually exercised
    by the published numbers; it would only matter if the data changed.)
    """
    n = len(all_rows)
    if n == 0:
        raise ValueError("pick_best_practice() requires at least one row, got an empty list")
    excluded_count = n // 4  # worst quartile by Worst DD (deepest/most negative)
    ranked_by_dd = sorted(all_rows, key=lambda r: r["Worst DD"])  # most negative (worst) first
    candidates = ranked_by_dd[excluded_count:]  # index-based exclusion of the worst quartile
    if not candidates:
        raise ValueError(
            f"pick_best_practice() excluded all {n} row(s) (excluded_count={excluded_count}); "
            "no candidates remain to pick a best practice from"
        )
    best = max(candidates, key=lambda r: r["Avg TWR"])
    return best, excluded_count


if __name__ == "__main__":
    sma_variants = build_sma_variants()
    print(f"Running SMA sweep ({len(sma_variants)} variants)...")
    sma_rows = []
    for i, variant in enumerate(sma_variants, 1):
        row = run_variant(variant)
        print(f"  [{i}/{len(sma_variants)}] {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = "SMA"
            sma_rows.append(row)

    ema_variants = build_ema_variants()
    print(f"Running EMA sweep ({len(ema_variants)} variants)...")
    ema_rows = []
    for i, variant in enumerate(ema_variants, 1):
        row = run_variant(variant)
        print(f"  [{i}/{len(ema_variants)}] {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = "EMA"
            ema_rows.append(row)

    sma_table = render_table("SMA — ATR & Signal Sweep (3x Leverage)", sma_rows)
    ema_table = render_table("EMA — ATR & Signal Sweep (3x Leverage)", ema_rows)

    all_rows = sma_rows + ema_rows
    best, excluded_count = pick_best_practice(all_rows)
    best_line = (
        f"BEST PRACTICE: {best['Strategy']} | ATR={best['ATR']} | Signal={best['Signal']} | T+2={best['T+2']}\n"
        f"  Avg TWR: {best['Avg TWR']:.2f}% | Worst DD: {best['Worst DD']:.2f}% | Avg Trades: {best['Avg Trades']:.0f}\n"
        f"  (highest Avg TWR among the {len(all_rows) - excluded_count} variants remaining after "
        f"excluding the {excluded_count} deepest-drawdown outliers out of {len(all_rows)} total)"
    )

    full_output = best_line + "\n\n---\n\n" + sma_table + "\n\n---\n\n" + ema_table
    print("\n" + full_output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"\nWritten to {OUTPUT_PATH}")
