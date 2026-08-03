"""
Rolling-window validation for the trailing-stop configurations that
out-performed out-of-sample, which the original validation never covered.

backtest/trailing_stop_validate.py ran this project's standing 172-window
rolling methodology for exactly one candidate, (8%, 60d) -- the pick
docs/trailing-stop-loss-out-of-sample-2026-08-02.md later showed ranks only
#20 of 29 out-of-sample. The configurations that actually performed best
out-of-sample ((10%, 40d), (12%, 20d)) have never been through the rolling
aggregate at all. This script closes that gap.

It also tests the "robust region" hypothesis rather than individual points:
all four corners of the 10-12% x 20-40d neighborhood are run, so the
question becomes "does this whole region beat baseline on the full
aggregate" -- a claim that survives the point-selection problem which two
independent selection procedures have now failed to solve. (8%, 60d) is
included as a cross-check: it should reproduce
docs/trailing-stop-loss-finding-2026-08-01.md's already-published numbers
(Avg TWR 23.43%, Worst DD -64.78%), confirming this script computes the
same thing the earlier one did.

Reuses SMATrendFollowing / run_experiment_suite / warmup_aware_start_dates /
summarize_rolling_results from backtest.strat_backtest -- no engine changes.
Pre-tax (apply_tax defaults False), matching README's stated convention.

Run manually:
    python backtest/trailing_stop_region_validate.py
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

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_region_validate_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

# (pct, cooldown, note). The four 10-12% x 20-40d corners test the region;
# (8%, 60d) is the published pick, carried only as a reproduction check
# against the earlier single-candidate validation.
VARIANTS = [
    (0.08, 60, "published pick -- reproduction check vs. trailing_stop_validate.py"),
    (0.10, 20, "region corner"),
    (0.10, 40, "pre-2016 selection winner; OOS rank #3/29"),
    (0.12, 20, "best OOS performer (rank #1/29)"),
    (0.12, 40, "region corner"),
]

WORST_BAND_START = pd.Timestamp("1998-01-01")
WORST_BAND_END = pd.Timestamp("2001-12-31")


def build_strategies():
    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    strategies = [baseline]
    for pct, cooldown, _ in VARIANTS:
        strategies.append(SMATrendFollowing(
            sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
            trailing_stop_pct=pct, trailing_stop_cooldown_days=cooldown,
        ))
    return strategies


if __name__ == "__main__":
    start_dates = warmup_aware_start_dates([BASE_TICKER, SIGNAL_TICKER], PERIOD_YEARS)
    strategies = build_strategies()

    print(f"Running {len(start_dates)}-window rolling backtest for {len(strategies)} strategies...")
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)

    # summarize_rolling_results iterates `strategies` in order and appends one
    # row per strategy, so index 0 is baseline and 1..N align with VARIANTS.
    baseline_row = summary[0]
    notes = ["baseline (no trailing stop)"] + [note for _, _, note in VARIANTS]

    lines = [f"### Trailing-Stop Region Rolling-Window Validation ({len(df_res)} windows, ^NDX/3x, S&P signal, pre-tax)", "",
             "| Config | Avg TWR | vs. baseline | Med TWR | Worst TWR | Worst DD | Avg Trades | Note |",
             "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
    for i, s in enumerate(summary):
        if i == 0:
            label = "baseline"
        else:
            pct, cooldown, _ = VARIANTS[i - 1]
            label = f"{pct:.0%}, {cooldown}d"
        delta = s["Avg TWR"] - baseline_row["Avg TWR"]
        delta_str = "--" if i == 0 else f"{delta:+.2f}pp"
        lines.append(
            f"| {label} | {s['Avg TWR']:.2f}% | {delta_str} | {s['Med TWR']:.2f}% "
            f"| {s['Worst TWR']:.2f}% | {s['Worst DD']:.2f}% | {s['Avg Trades']:.1f} | {notes[i]} |"
        )

    # Per-window drawdown win rate. The aggregate "Worst DD" column above is a
    # single worst-case scalar and hides whether a config helps drawdown
    # generally or only in one window -- which turns out to be the decisive
    # question here, since the aggregate alone made the 10-12% configs look
    # merely neutral on drawdown rather than actively harmful.
    baseline_dd_col = f"{strategies[0].name} Max DD (%)"
    lines += ["", "### Per-window drawdown vs. baseline (172 windows each)", "",
              "| Config | Windows improved | Windows worsened | Identical | Mean Max DD |",
              "| :--- | ---: | ---: | ---: | ---: |"]
    for i, s in enumerate(strategies):
        if i == 0:
            lines.append(f"| baseline | -- | -- | -- | {df_res[baseline_dd_col].mean():.2f}% |")
            continue
        col = f"{s.name} Max DD (%)"
        if col not in df_res.columns:
            continue
        # Max DD is negative; a less-negative value is a smaller drawdown.
        better = int((df_res[col] > df_res[baseline_dd_col]).sum())
        worse = int((df_res[col] < df_res[baseline_dd_col]).sum())
        same = int((df_res[col] == df_res[baseline_dd_col]).sum())
        label = f"{VARIANTS[i-1][0]:.0%}, {VARIANTS[i-1][1]}d"
        lines.append(f"| {label} | {better} | {worse} | {same} | {df_res[col].mean():.2f}% |")

    # Segmentation: worst-window start-date band vs. everything else -- same
    # split trailing_stop_validate.py used, so the two are directly comparable.
    df_res["Start Date"] = pd.to_datetime(df_res["Start Date"])
    in_band_mask = (df_res["Start Date"] >= WORST_BAND_START) & (df_res["Start Date"] <= WORST_BAND_END)
    in_band = df_res[in_band_mask]
    out_band = df_res[~in_band_mask]

    lines += ["", f"### Segmentation: worst-window start-date band ({WORST_BAND_START.date()} to {WORST_BAND_END.date()}) vs. rest", "",
              "| Config | In-band Avg TWR | Other-starts Avg TWR | In-band N | Other N |",
              "| :--- | ---: | ---: | ---: | ---: |"]
    for i, s in enumerate(strategies):
        ret_col = f"{s.name} TWR (%)"
        if ret_col not in df_res.columns:
            continue
        label = "baseline" if i == 0 else f"{VARIANTS[i-1][0]:.0%}, {VARIANTS[i-1][1]}d"
        lines.append(
            f"| {label} | {in_band[ret_col].mean():.2f}% | {out_band[ret_col].mean():.2f}% "
            f"| {len(in_band)} | {len(out_band)} |"
        )

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
