"""
Tax-aware out-of-sample re-run for the trailing-stop mechanism.

Follow-up to backtest/trailing_stop_out_of_sample.py
(docs/trailing-stop-loss-out-of-sample-2026-08-02.md), which evaluated all
29 variants pre-tax (Backtester's default, apply_tax=False) and flagged
that as an open caveat -- every prior trailing-stop finding warned the
gross/pre-tax edge might not survive costs. This script re-runs the exact
same 29-variant, CUTOFF-to-today evaluation with apply_tax=True (built-in
Backtester feature: TAX_SHORT_TERM_RATE=25% on gains from trades held
<=365 days, TAX_LONG_TERM_RATE=15% otherwise -- see strat_backtest.py).
No engine change; no commission/slippage modeling (that remains a distinct,
unaddressed follow-up per the original design spec's explicit scope note).

Reuses build_variants(), CUTOFF, BASE_TICKER, SIGNAL_TICKER, CONFIG,
PUBLISHED_PCT/PUBLISHED_COOLDOWN from trailing_stop_out_of_sample.py rather
than re-deriving them, and Backtester directly from strat_backtest.py for
the after-tax eval loop (mirrors trailing_stop_out_of_sample.py's own
run_evaluation_phase, not duplicated from it, since apply_tax=True changes
the call).

Run manually:
    python backtest/trailing_stop_tax_aware_out_of_sample.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester
from backtest.trailing_stop_out_of_sample import (
    build_variants, run_evaluation_phase, CUTOFF, BASE_TICKER, SIGNAL_TICKER,
    CONFIG, PUBLISHED_PCT, PUBLISHED_COOLDOWN,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_tax_aware_out_of_sample_output.md"

# Pre-2016 selection-phase winner from trailing_stop_out_of_sample_output.md
# -- recorded here rather than re-running the selection phase, since that
# phase doesn't use apply_tax and its outcome is unchanged by this check.
SELECTION_TOP_PCT = 0.10
SELECTION_TOP_COOLDOWN = 40


def run_evaluation_phase_after_tax(variants, period_years):
    """Same evaluation loop as trailing_stop_out_of_sample.run_evaluation_phase,
    but with apply_tax=True on every Backtester call."""
    rows = []
    for pct, cooldown, strat in variants:
        env = Backtester(
            base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
            start_date=CUTOFF.strftime("%Y-%m-%d"), period_years=period_years,
            leverage=CONFIG["leverage"], expense_ratio=CONFIG["expense"],
            initial_fund=10000, apply_tax=True, verbose=False,
        )
        res = env.run(strat)
        if res is None:
            continue
        rows.append({
            "pct": pct, "cooldown": cooldown,
            "TWR": res["strategy_twr"], "Max DD": res["max_drawdown"],
            "Trades": res.get("total_trades", 0),
            "Tax Paid": res.get("total_tax_paid", 0.0),
        })
    return rows


def render_comparison_table(pretax_rows, aftertax_rows):
    pretax_by_key = {(r["pct"], r["cooldown"]): r for r in pretax_rows}
    aftertax_sorted = sorted(aftertax_rows, key=lambda r: -r["TWR"])
    lines = ["### Pre-Tax vs. After-Tax Out-of-Sample Comparison (CUTOFF-to-today)", "",
             "| Pct | Cooldown | Pre-Tax TWR | After-Tax TWR | Tax Drag (pp) | After-Tax Max DD | Trades | Tax Paid | |",
             "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
    for rank, r in enumerate(aftertax_sorted, 1):
        key = (r["pct"], r["cooldown"])
        pre = pretax_by_key.get(key)
        pct_label = "baseline" if r["pct"] is None else f"{r['pct']:.0%}"
        cd_label = "-" if r["cooldown"] is None else f"{r['cooldown']}d"
        drag = (pre["TWR"] - r["TWR"]) if pre else float("nan")
        markers = []
        if r["pct"] == SELECTION_TOP_PCT and r["cooldown"] == SELECTION_TOP_COOLDOWN:
            markers.append("<- PRE-2016 SELECTION-PHASE WINNER")
        if r["pct"] == PUBLISHED_PCT and r["cooldown"] == PUBLISHED_COOLDOWN:
            markers.append("<- PUBLISHED (8%, 60d) PICK")
        marker = " ".join(markers)
        pre_twr_str = f"{pre['TWR']:.2f}%" if pre else "n/a"
        lines.append(
            f"| {pct_label} | {cd_label} | {pre_twr_str} | {r['TWR']:.2f}% | {drag:+.2f} "
            f"| {r['Max DD']:.2f}% | {r['Trades']:.0f} | ${r['Tax Paid']:,.0f} "
            f"| rank #{rank}/{len(aftertax_sorted)} {marker} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    variants = build_variants()

    print(f"CUTOFF: {CUTOFF.date()} | today: {pd.Timestamp.today().date()}")
    print(f"Pre-tax evaluation phase: {len(variants)} variants, single run {CUTOFF.date()} to today...")
    pretax_rows, period_years = run_evaluation_phase(variants)
    print(f"period_years: {period_years}")

    print(f"\nAfter-tax evaluation phase: {len(variants)} variants, single run {CUTOFF.date()} to today...")
    aftertax_rows = run_evaluation_phase_after_tax(variants, period_years)

    table = render_comparison_table(pretax_rows, aftertax_rows)
    print("\n" + table)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(table)
    print(f"\nWritten to {OUTPUT_PATH}")
