"""
Tests whether Table 4's mechanically-selected "Best Practice" strategy
config generalizes to unseen data, or was curve-fit to the history it was
selected against.

Run manually:
    python backtest/validate_out_of_sample.py

Selects a winner using only pre-CUTOFF window history (26-year windows
ending by CUTOFF, so no calendar overlap with the evaluation period), then
evaluates every variant once on the untouched CUTOFF-to-end_dt period
(end_dt is CUTOFF plus the whole number of years elapsed since CUTOFF as of
the run date — see __main__). Writes a report to stdout AND
backtest/out_of_sample_output.md.

NOTE ON INTERPRETATION: the CUTOFF-to-end_dt evaluation period is NOT
disjoint from Table 4's own 172-window selection sample (most of those
windows extend past CUTOFF), so evaluating Table 4's *published* pick on
this period is an in-sample sub-period check, not a genuine holdout test.
Only the winner selected by run_variant_selection() above — using windows
that end entirely before CUTOFF — is evaluated out-of-sample in the strict
sense. See docs/out-of-sample-validation-2026-07-28.md for the full
writeup.
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester, warmup_aware_start_dates
from backtest.generate_signal_comparison import (
    build_sma_variants, build_ema_variants, run_variant, pick_best_practice,
    PERIOD_YEARS, LEVERAGE_CONFIG,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "out_of_sample_output.md"

CUTOFF = pd.Timestamp("2016-01-01")


def selection_start_dates(tickers):
    """Candidate start dates whose full PERIOD_YEARS-year window ends by
    CUTOFF — i.e. no calendar overlap with this script's own CUTOFF-to-end_dt
    evaluation period. Filters warmup_aware_start_dates() rather than
    reimplementing the warmup-floor logic."""
    all_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    max_start = CUTOFF - pd.DateOffset(years=PERIOD_YEARS)
    return all_dates[all_dates <= max_start]


def run_variant_selection(variant):
    """Selection-phase run: the same rolling-window sweep run_variant()
    already does, restricted to the pre-CUTOFF window set."""
    signal_ticker = variant["signal_ticker"]
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    dates = selection_start_dates(tickers)
    return run_variant(variant, start_dates=dates)


def run_variant_evaluation(variant, period_years):
    """Evaluation-phase run: a single, non-rolling backtest over the
    untouched CUTOFF-to-end_dt period, where end_dt = CUTOFF +
    DateOffset(years=period_years). period_years is computed once by the
    caller from the actual run date (see __main__) and passed in here — a
    hardcoded value that overshoots the run date would cause
    Backtester.run()'s window-length check to reject this window as "too
    short" (no future data exists to fill a longer request).

    period_years must be a whole integer, floored from the actual elapsed
    time: pd.DateOffset(years=...), used internally by Backtester.__init__,
    raises ValueError on a fractional years value. Flooring makes the
    window a few months shorter than the absolute maximum available
    (roughly 7 months as of a 2026-07-28 run against a 2016-01-01 cutoff)
    — negligible for this analysis, and keeps the slice safely within
    Backtester.run()'s 98%-span window-length-validation check.
    """
    strat = variant["strategy"]
    signal_ticker = variant["signal_ticker"]
    env = Backtester(
        base_ticker="^NDX",
        signal_ticker=signal_ticker,
        start_date=CUTOFF.strftime("%Y-%m-%d"),
        period_years=period_years,
        leverage=LEVERAGE_CONFIG["leverage"],
        expense_ratio=LEVERAGE_CONFIG["expense"],
        initial_fund=10000,
        apply_tax=False,
        verbose=False,
    )
    res = env.run(strat)
    if res is None:
        return None
    row = dict(variant["row"])
    row["TWR"] = res["strategy_twr"]
    row["Max DD"] = res["max_drawdown"]
    row["Trades"] = res.get("total_trades", 0)
    return row


def render_evaluation_table(title, rows, winner_row):
    rows_sorted = sorted(rows, key=lambda r: r["TWR"], reverse=True)
    lines = [f"### {title}", "",
             "| ATR | Signal | T+2 | TWR | Max DD | Trades |",
             "| :--- | :--- | :--- | ---: | ---: | ---: |"]
    for r in rows_sorted:
        marker = " **<- IN-SAMPLE WINNER**" if r is winner_row else ""
        lines.append(
            f"| {r['ATR']} | {r['Signal']} | {r['T+2']} | {r['TWR']:.2f}% "
            f"| {r['Max DD']:.2f}% | {r['Trades']:.0f} |{marker}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    # Resolve every date/count that depends on "now" exactly once, up front,
    # and print them clearly — pd.Timestamp.today() used to be called twice
    # (once implicitly inside warmup_aware_start_dates() for the selection
    # phase, once here for the evaluation phase) with neither value logged,
    # so a re-run on a different date would silently produce different
    # numbers with no record of what changed.
    run_today = pd.Timestamp.today()
    period_years = int((run_today - CUTOFF).days / 365.25)
    end_dt = CUTOFF + pd.DateOffset(years=period_years)

    sma_variants = build_sma_variants()
    ema_variants = build_ema_variants()
    all_variants = [(v, "SMA") for v in sma_variants] + [(v, "EMA") for v in ema_variants]

    sel_dates_ndx = selection_start_dates(["^NDX"])

    print(
        f"RESOLVED RUN PARAMETERS: run date={run_today.date()} | CUTOFF={CUTOFF.date()} | "
        f"evaluation end_dt={end_dt.date()} (period_years={period_years}, floored) | "
        f"selection-phase candidate windows={len(sel_dates_ndx)} "
        f"({sel_dates_ndx[0].date()} to {sel_dates_ndx[-1].date()})"
    )
    print(f"Selection phase: {len(all_variants)} variants, windows ending by {CUTOFF.date()}...")

    selection_rows = []
    for i, (variant, family) in enumerate(all_variants, 1):
        row = run_variant_selection(variant)
        print(f"  [{i}/{len(all_variants)}] {family} {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = family
            selection_rows.append(row)

    winner, excluded_count = pick_best_practice(selection_rows)
    print(f"\nIN-SAMPLE WINNER: {winner['Strategy']} | ATR={winner['ATR']} | Signal={winner['Signal']} | T+2={winner['T+2']}")
    print(f"  Selection-phase Avg TWR: {winner['Avg TWR']:.2f}% | Worst DD: {winner['Worst DD']:.2f}%")
    print(f"  Excluded by drawdown screen: {excluded_count} of {len(selection_rows)} selection-phase variants")

    print(f"\nEvaluation phase: {len(all_variants)} variants, single run {CUTOFF.date()} to {end_dt.date()}...")
    eval_rows = []
    winner_eval_row = None
    for i, (variant, family) in enumerate(all_variants, 1):
        row = run_variant_evaluation(variant, period_years)
        print(f"  [{i}/{len(all_variants)}] {family} {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = family
            eval_rows.append(row)
            is_winner = (
                family == winner["Strategy"] and row["ATR"] == winner["ATR"]
                and row["Signal"] == winner["Signal"] and row["T+2"] == winner["T+2"]
            )
            if is_winner:
                winner_eval_row = row

    eval_rows_sorted = sorted(eval_rows, key=lambda r: r["TWR"], reverse=True)
    winner_rank = next(
        (i for i, r in enumerate(eval_rows_sorted, 1) if r is winner_eval_row), None
    )
    oos_best = eval_rows_sorted[0] if eval_rows_sorted else None

    verdict_lines = [
        f"RESOLVED RUN PARAMETERS: run date={run_today.date()} | CUTOFF={CUTOFF.date()} | "
        f"evaluation end_dt={end_dt.date()} (period_years={period_years}, floored) | "
        f"selection-phase candidate windows={len(sel_dates_ndx)} "
        f"({sel_dates_ndx[0].date()} to {sel_dates_ndx[-1].date()})",
        f"IN-SAMPLE WINNER: {winner['Strategy']} | ATR={winner['ATR']} | Signal={winner['Signal']} | T+2={winner['T+2']}",
        f"  Selection-phase (windows ending by {CUTOFF.date()}): "
        f"Avg TWR {winner['Avg TWR']:.2f}% | Worst DD {winner['Worst DD']:.2f}% "
        f"({excluded_count} of {len(selection_rows)} variants excluded by the drawdown screen)",
    ]
    if winner_eval_row is not None:
        verdict_lines.append(
            f"  Out-of-sample ({CUTOFF.date()} to {end_dt.date()}): "
            f"TWR {winner_eval_row['TWR']:.2f}% | Max DD {winner_eval_row['Max DD']:.2f}% "
            f"-> rank #{winner_rank} of {len(eval_rows_sorted)}"
        )
    else:
        verdict_lines.append("  Out-of-sample: NO DATA (window rejected)")
    if oos_best is not None:
        matches = winner_eval_row is not None and oos_best is winner_eval_row
        if matches:
            verdict_lines.append("  Out-of-sample best variant MATCHES the in-sample winner.")
        else:
            verdict_lines.append(
                f"  Out-of-sample best variant DIFFERS: {oos_best['Strategy']} | ATR={oos_best['ATR']} "
                f"| Signal={oos_best['Signal']} | T+2={oos_best['T+2']} "
                f"(TWR {oos_best['TWR']:.2f}%, Max DD {oos_best['Max DD']:.2f}%)"
            )

    sma_eval = [r for r in eval_rows if r["Strategy"] == "SMA"]
    ema_eval = [r for r in eval_rows if r["Strategy"] == "EMA"]
    sma_table = render_evaluation_table("SMA — Out-of-Sample Evaluation", sma_eval, winner_eval_row)
    ema_table = render_evaluation_table("EMA — Out-of-Sample Evaluation", ema_eval, winner_eval_row)

    full_output = "\n".join(verdict_lines) + "\n\n---\n\n" + sma_table + "\n\n---\n\n" + ema_table
    print("\n" + full_output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"\nWritten to {OUTPUT_PATH}")
