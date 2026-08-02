"""
Out-of-sample validation for the trailing-stop mechanism (see
docs/superpowers/specs/2026-08-02-trailing-stop-out-of-sample-design.md).
Reuses the calendar-cutoff design from backtest/validate_out_of_sample.py
(docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md):
selects a (pct, cooldown) candidate using only rolling windows whose
26-year span ends by CUTOFF, then evaluates baseline + all 28 combinations
on a single non-rolling backtest over the untouched CUTOFF-to-today period.

Run manually:
    python backtest/trailing_stop_out_of_sample.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, Backtester, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_out_of_sample_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

CUTOFF = pd.Timestamp("2016-01-01")

PCT_GRID = [0.05, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20]
COOLDOWN_GRID = [10, 20, 40, 60]

# Today's already-published candidate (docs/trailing-stop-loss-finding-2026-08-01.md),
# selected using the full, un-split history -- flagged separately from
# whatever this script's pre-2016-only selection phase picks.
PUBLISHED_PCT = 0.08
PUBLISHED_COOLDOWN = 60


def make_strategy(pct=None, cooldown=None):
    if pct is None:
        return SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    return SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                              trailing_stop_pct=pct, trailing_stop_cooldown_days=cooldown)


def build_variants():
    """[(pct, cooldown, strategy), ...] -- (None, None, ...) is baseline, first entry."""
    variants = [(None, None, make_strategy())]
    for pct in PCT_GRID:
        for cooldown in COOLDOWN_GRID:
            variants.append((pct, cooldown, make_strategy(pct, cooldown)))
    return variants


def selection_start_dates():
    """Windows whose full PERIOD_YEARS-year span ends by CUTOFF -- no calendar
    overlap with the CUTOFF-to-today evaluation period."""
    all_dates = warmup_aware_start_dates([BASE_TICKER, SIGNAL_TICKER], PERIOD_YEARS)
    max_start = CUTOFF - pd.DateOffset(years=PERIOD_YEARS)
    return all_dates[all_dates <= max_start]


def run_selection_phase(variants, start_dates):
    """Returns ({(pct, cooldown): avg_twr}, n_windows_actually_used), using
    ONLY the given (pre-cutoff) start_dates."""
    strategies = [strat for _, _, strat in variants]
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)
    # summarize_rolling_results iterates `strategies` in order and appends one
    # row per strategy, so zip(variants, summary) aligns positionally.
    twr_by_key = {}
    for (pct, cooldown, _), row in zip(variants, summary):
        twr_by_key[(pct, cooldown)] = row["Avg TWR"]
    return twr_by_key, len(df_res)


def grid_neighbor_values(twr_by_key, baseline_twr, pct, cooldown):
    """Improvement-over-baseline for the immediate grid-adjacent pct and
    cooldown values (whichever side(s) exist -- grid edges only have one)."""
    pct_idx = PCT_GRID.index(pct)
    cooldown_idx = COOLDOWN_GRID.index(cooldown)
    pct_neighbors = []
    for i in (pct_idx - 1, pct_idx + 1):
        if 0 <= i < len(PCT_GRID):
            n_pct = PCT_GRID[i]
            pct_neighbors.append((n_pct, cooldown, twr_by_key[(n_pct, cooldown)] - baseline_twr))
    cooldown_neighbors = []
    for i in (cooldown_idx - 1, cooldown_idx + 1):
        if 0 <= i < len(COOLDOWN_GRID):
            n_cd = COOLDOWN_GRID[i]
            cooldown_neighbors.append((pct, n_cd, twr_by_key[(pct, n_cd)] - baseline_twr))
    return pct_neighbors, cooldown_neighbors


def render_selection_table(twr_by_key, n_windows):
    baseline_twr = twr_by_key[(None, None)]
    rows = []
    for pct in PCT_GRID:
        for cooldown in COOLDOWN_GRID:
            improvement = twr_by_key[(pct, cooldown)] - baseline_twr
            pct_n, cd_n = grid_neighbor_values(twr_by_key, baseline_twr, pct, cooldown)
            rows.append({"pct": pct, "cooldown": cooldown, "improvement": improvement,
                         "pct_neighbors": pct_n, "cooldown_neighbors": cd_n})
    rows.sort(key=lambda r: -r["improvement"])

    def fmt_neighbors(neighbors):
        if not neighbors:
            return "n/a"
        return "; ".join(f"({p:.0%},{c}d)={v:+.2f}pp" for p, c, v in neighbors)

    lines = [f"### Selection Phase: Pre-{CUTOFF.date()} Rolling Avg TWR Improvement over Baseline ({n_windows} windows)", "",
             f"Baseline (no trailing stop) selection-phase Avg TWR: {baseline_twr:.2f}%", "",
             "| Pct | Cooldown | Improvement (pp) | Pct-neighbor(s) | Cooldown-neighbor(s) |",
             "| ---: | ---: | ---: | :--- | :--- |"]
    for r in rows:
        lines.append(
            f"| {r['pct']:.0%} | {r['cooldown']}d | {r['improvement']:+.2f} "
            f"| {fmt_neighbors(r['pct_neighbors'])} | {fmt_neighbors(r['cooldown_neighbors'])} |"
        )
    top = rows[0]
    return "\n".join(lines), top


def run_evaluation_phase(variants):
    """Single non-rolling backtest, CUTOFF to today, for every variant.
    period_years is floored to a whole integer -- Backtester.__init__'s
    pd.DateOffset(years=...) raises ValueError on a fractional value, and a
    non-floored value would overshoot today, tripping Backtester.run()'s
    98%-span window-length-validation check (no future data exists to fill
    a longer request). See docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md
    for the original derivation of this constraint -- reused verbatim here."""
    period_years = int((pd.Timestamp.today() - CUTOFF).days / 365.25)
    rows = []
    for pct, cooldown, strat in variants:
        env = Backtester(
            base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
            start_date=CUTOFF.strftime("%Y-%m-%d"), period_years=period_years,
            leverage=CONFIG["leverage"], expense_ratio=CONFIG["expense"],
            initial_fund=10000, apply_tax=False, verbose=False,
        )
        res = env.run(strat)
        if res is None:
            continue
        rows.append({
            "pct": pct, "cooldown": cooldown,
            "TWR": res["strategy_twr"], "Max DD": res["max_drawdown"],
            "Trades": res.get("total_trades", 0),
        })
    return rows, period_years


def render_evaluation_table(eval_rows, selection_top):
    rows_sorted = sorted(eval_rows, key=lambda r: -r["TWR"])
    lines = ["### Evaluation Phase: Out-of-Sample Single Backtest (CUTOFF-to-today)", "",
             "| Pct | Cooldown | TWR | Max DD | Trades | |",
             "| ---: | ---: | ---: | ---: | ---: | :--- |"]
    for rank, r in enumerate(rows_sorted, 1):
        pct_label = "baseline" if r["pct"] is None else f"{r['pct']:.0%}"
        cd_label = "-" if r["cooldown"] is None else f"{r['cooldown']}d"
        markers = []
        if r["pct"] == selection_top["pct"] and r["cooldown"] == selection_top["cooldown"]:
            markers.append("<- PRE-2016 SELECTION-PHASE WINNER")
        if r["pct"] == PUBLISHED_PCT and r["cooldown"] == PUBLISHED_COOLDOWN:
            markers.append("<- PUBLISHED (8%, 60d) PICK")
        marker = " ".join(markers)
        lines.append(
            f"| {pct_label} | {cd_label} | {r['TWR']:.2f}% | {r['Max DD']:.2f}% "
            f"| {r['Trades']:.0f} | rank #{rank}/{len(rows_sorted)} {marker} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    variants = build_variants()

    print(f"CUTOFF: {CUTOFF.date()} | today: {pd.Timestamp.today().date()}")
    sel_dates = selection_start_dates()
    print(f"Selection phase: {len(variants)} variants, {len(sel_dates)} windows ending by {CUTOFF.date()}...")
    twr_by_key, n_sel_windows = run_selection_phase(variants, sel_dates)
    selection_table, selection_top = render_selection_table(twr_by_key, n_sel_windows)
    print("\n" + selection_table)
    print(f"\nMechanical top pick: ({selection_top['pct']:.0%}, {selection_top['cooldown']}d), "
          f"improvement {selection_top['improvement']:+.2f}pp -- inspect the neighbor columns above "
          f"for fragility before trusting this at face value.")

    print(f"\nEvaluation phase: {len(variants)} variants, single run {CUTOFF.date()} to today...")
    eval_rows, eval_period_years = run_evaluation_phase(variants)
    evaluation_table = render_evaluation_table(eval_rows, selection_top)
    print("\n" + evaluation_table)

    output = "\n\n".join([selection_table, evaluation_table])
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
