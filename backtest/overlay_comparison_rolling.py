"""
Head-to-head rolling-window comparison of the two experimental overlays on
SMATrendFollowing -- the trailing stop and the VIX-adaptive T+2 bypass --
against the unmodified baseline, on this project's standing 172-window
methodology.

Motivation: these two overlays have never been compared on equal footing.
The trailing stop now has a rolling aggregate
(docs/trailing-stop-loss-region-validation-2026-08-03.md), an out-of-sample
check, and a tax-aware re-run. `vix_threshold` has none of those -- it was
explored in the 2026-08-01 session (docs/session-handover-2026-08-01.md
Phase 5) via event-relative decline and a single full-history run, then
shelved when segmentation suggested its benefit was ~COVID-specific. This
script puts both on the same 172 windows.

Two known confounders are measured rather than assumed:

1. VIX data only exists from 1990 onward (see strat_backtest.py's ^VIX
   cache note). Every one of the 172 windows is 26 years long and starts
   between 1986-04-29 and 2000-07-28, so all windows contain post-1990
   history -- but windows starting before 1990 have a NaN-VIX prefix during
   which the bypass silently cannot fire. The bypass therefore has less
   calendar exposure in early windows.
2. The handover's skeptical finding was that VIX-adaptive's benefit is
   concentrated in windows containing COVID. That segmentation (start
   >= 1994, i.e. the 26-year span reaches 2020) is reproduced here for
   every strategy, so the same question is asked of the trailing stop too.

All three VIX thresholds from the original exploration (25/30/35) are run,
to test parameter stability the same way the trailing-stop grid was tested.

Pre-tax, matching README's stated convention. Reuses SMATrendFollowing /
run_experiment_suite / warmup_aware_start_dates / summarize_rolling_results
from backtest.strat_backtest -- no engine changes.

Run manually:
    python backtest/overlay_comparison_rolling.py
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

OUTPUT_PATH = REPO_ROOT / "backtest" / "overlay_comparison_rolling_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

# A window's 26-year span reaches 2020 (COVID) iff it starts in 1994 or
# later -- the same split docs/session-handover-2026-08-01.md used when it
# found VIX-adaptive's benefit was ~COVID-specific.
COVID_START_CUTOFF = pd.Timestamp("1994-01-01")

# (label, kwargs, note)
VARIANTS = [
    ("baseline", {}, "unmodified live bot.py config"),
    ("stop 8%, 60d", {"trailing_stop_pct": 0.08, "trailing_stop_cooldown_days": 60},
     "drawdown winner: 172/172 windows improved"),
    ("stop 10%, 40d", {"trailing_stop_pct": 0.10, "trailing_stop_cooldown_days": 40},
     "best rolling return, but worsens drawdown in 168/172"),
    ("stop 12%, 20d", {"trailing_stop_pct": 0.12, "trailing_stop_cooldown_days": 20},
     "best out-of-sample return; drawdown a coin flip"),
    ("VIX>25", {"vix_threshold": 25}, "T+2 bypass on high-VIX days"),
    ("VIX>30", {"vix_threshold": 30}, "best single threshold per 2026-08-01 exploration"),
    ("VIX>35", {"vix_threshold": 35}, "T+2 bypass on high-VIX days"),
]


def build_strategies():
    return [
        SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True, **kwargs)
        for _, kwargs, _ in VARIANTS
    ]


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
    baseline_row = summary[0]

    lines = [f"### Overlay Comparison: Rolling-Window Aggregate ({len(df_res)} windows, ^NDX/3x, S&P signal, pre-tax)", "",
             "| Config | Avg TWR | vs. baseline | Med TWR | Worst TWR | Worst DD | Avg Trades | Note |",
             "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
    for i, s in enumerate(summary):
        label, _, note = VARIANTS[i]
        delta = s["Avg TWR"] - baseline_row["Avg TWR"]
        delta_str = "--" if i == 0 else f"{delta:+.2f}pp"
        lines.append(
            f"| {label} | {s['Avg TWR']:.2f}% | {delta_str} | {s['Med TWR']:.2f}% "
            f"| {s['Worst TWR']:.2f}% | {s['Worst DD']:.2f}% | {s['Avg Trades']:.1f} | {note} |"
        )

    # Per-window drawdown win rate. The aggregate Worst DD is one worst-case
    # scalar; for the trailing stop this distinction turned out to be
    # decisive, so the same lens is applied to every overlay here.
    baseline_dd_col = f"{strategies[0].name} Max DD (%)"
    lines += ["", "### Per-window drawdown vs. baseline", "",
              "| Config | Improved | Worsened | Identical | Mean Max DD |",
              "| :--- | ---: | ---: | ---: | ---: |"]
    for i, s in enumerate(strategies):
        col = f"{s.name} Max DD (%)"
        if col not in df_res.columns:
            continue
        label = VARIANTS[i][0]
        if i == 0:
            lines.append(f"| {label} | -- | -- | -- | {df_res[col].mean():.2f}% |")
            continue
        # Max DD is negative; less negative = smaller drawdown = better.
        better = int((df_res[col] > df_res[baseline_dd_col]).sum())
        worse = int((df_res[col] < df_res[baseline_dd_col]).sum())
        same = int((df_res[col] == df_res[baseline_dd_col]).sum())
        lines.append(f"| {label} | {better} | {worse} | {same} | {df_res[col].mean():.2f}% |")

    # COVID segmentation: does each overlay's benefit survive outside the
    # windows containing the one event VIX-adaptive was suspected of fitting?
    df_res["Start Date"] = pd.to_datetime(df_res["Start Date"])
    covid_mask = df_res["Start Date"] >= COVID_START_CUTOFF
    covid = df_res[covid_mask]
    no_covid = df_res[~covid_mask]

    base_ret_col = f"{strategies[0].name} TWR (%)"
    base_covid = covid[base_ret_col].mean()
    base_no_covid = no_covid[base_ret_col].mean()

    lines += ["", f"### Segmentation: windows containing COVID (start >= {COVID_START_CUTOFF.date()}) vs. not", "",
              f"Baseline Avg TWR: {base_covid:.2f}% (COVID windows, N={len(covid)}) | "
              f"{base_no_covid:.2f}% (non-COVID windows, N={len(no_covid)})", "",
              "| Config | COVID-window improvement | Non-COVID improvement | Gap |",
              "| :--- | ---: | ---: | ---: |"]
    for i, s in enumerate(strategies):
        if i == 0:
            continue
        col = f"{s.name} TWR (%)"
        if col not in df_res.columns:
            continue
        imp_covid = covid[col].mean() - base_covid
        imp_no_covid = no_covid[col].mean() - base_no_covid
        lines.append(
            f"| {VARIANTS[i][0]} | {imp_covid:+.2f}pp | {imp_no_covid:+.2f}pp "
            f"| {imp_covid - imp_no_covid:+.2f}pp |"
        )

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
