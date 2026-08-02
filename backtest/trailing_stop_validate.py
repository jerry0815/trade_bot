"""
Rolling-window validation for the trailing-stop candidate selected from
backtest/trailing_stop_sweep_output.md (see backtest/trailing_stop_sweep.py
and docs/superpowers/plans/2026-08-01-trailing-stop-loss.md Task 3 for the
selection procedure), plus a start-date-band segmentation check.

Segmentation note (see docs/superpowers/specs/2026-08-01-trailing-stop-loss-design.md
Component 4): all 172 rolling windows' 26-year spans already include the
dot-com period (2000-2002), so a "contains dot-com y/n" split has no
non-trivial groups. This instead segments by window START date: the
1998-01-01 to 2001-12-31 band (where Phase 4's worst-10 rolling windows for
the live SMA config all land) vs. all other starts.

Run manually:
    python backtest/trailing_stop_validate.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, run_experiment_suite, warmup_aware_start_dates,
    summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_validate_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

CANDIDATE_PCT = 0.08      # Re-derived from scratch against the corrected sweep (after the
                          # one-day-lookahead bug in _apply_trailing_stop was fixed). The
                          # mechanical top pick is again (5%, 60d, +53.62pp) and is again
                          # rejected by hand: its (5%, 40d) cooldown-neighbor scores only
                          # +1.77pp, a 30x non-monotonic cliff (the pre-fix numbers showed
                          # 8.6x here) -- the same fragility signature rejected for
                          # atr_spike_multiplier in Phase 6. (7%, 60d, +41.70pp) is rejected
                          # for the same reason (26x vs. (7%, 40d)=+1.57pp). (8%, 60d,
                          # +32.14pp) is the only survivor whose neighborhood is smooth on
                          # BOTH axes: (8%, 40d)=+21.65pp (1.48x) and (7%, 60d)=+41.70pp
                          # (0.77x) are both comparable in magnitude, not cliffs.
CANDIDATE_COOLDOWN = 60   # same pair as the pre-fix analysis happened to land on, but
                          # re-derived, not carried over

WORST_BAND_START = pd.Timestamp("1998-01-01")
WORST_BAND_END = pd.Timestamp("2001-12-31")


if __name__ == "__main__":
    start_dates = warmup_aware_start_dates([BASE_TICKER, SIGNAL_TICKER], PERIOD_YEARS)

    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    candidate = SMATrendFollowing(
        sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
        trailing_stop_pct=CANDIDATE_PCT, trailing_stop_cooldown_days=CANDIDATE_COOLDOWN,
    )
    strategies = [baseline, candidate]

    print(f"Running {len(start_dates)}-window rolling backtest for {len(strategies)} strategies...")
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]

    summary = summarize_rolling_results(df_res, strategies)

    # Report the number of windows that actually produced results, not the
    # number requested: run_experiment_suite drops windows with no usable data,
    # so len(start_dates) would silently overstate the count.
    lines = [f"### Trailing-Stop Rolling-Window Validation ({len(df_res)} windows, ^NDX/3x, S&P signal)", "",
             "| Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |",
             "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for s in summary:
        lines.append(
            f"| {s['Strategy']} | {s['Avg TWR']:.2f}% | {s['Med TWR']:.2f}% "
            f"| {s['Worst TWR']:.2f}% | {s['Worst DD']:.2f}% | {s['Avg Trades']:.1f} |"
        )

    # Segmentation: worst-window start-date band vs. everything else.
    df_res["Start Date"] = pd.to_datetime(df_res["Start Date"])
    in_band_mask = (df_res["Start Date"] >= WORST_BAND_START) & (df_res["Start Date"] <= WORST_BAND_END)
    in_band = df_res[in_band_mask]
    out_band = df_res[~in_band_mask]

    lines += ["", f"### Segmentation: worst-window start-date band ({WORST_BAND_START.date()} to {WORST_BAND_END.date()}) vs. rest", "",
              "| Strategy | Band | Avg TWR | N windows |",
              "| :--- | :--- | ---: | ---: |"]
    for s in strategies:
        ret_col = f"{s.name} TWR (%)"
        for label, sub in [(f"{WORST_BAND_START.date()} to {WORST_BAND_END.date()} starts", in_band),
                            ("Other starts", out_band)]:
            if ret_col in sub.columns and len(sub):
                lines.append(f"| {s.name} | {label} | {sub[ret_col].mean():.2f}% | {len(sub)} |")

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
