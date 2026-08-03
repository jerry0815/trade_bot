"""
Parameter-stability probe around the (8%, 60d) trailing-stop candidate.

docs/trailing-stop-loss-region-validation-2026-08-03.md found that the
drawdown effect reverses sign between adjacent grid points: (8%, 60d)
improves per-window drawdown in 172/172 rolling windows, while (10%, 40d)
and (10%, 20d) WORSEN it in 168/172. The original sweep grid
(5/7/8/10/12/15/20%) jumps straight from 8% to 10%, so nothing was ever
measured in between -- meaning it is currently unknown whether 8% sits on a
smooth gradient or on a cliff.

That distinction decides whether (8%, 60d) is adoptable. A cliff is the
same non-monotonic overfitting signature this project has already rejected
three times (Table 4's ATR sweep, Phase 6's atr_spike_multiplier, and the
trailing stop's own (5%, 60d) rejection).

This probe walks BOTH axes around the candidate at finer resolution than
the original grid:
  - stop width 6/7/8/9/10% at the fixed 60d cooldown (9% and 6% are new)
  - cooldown 40/60/80d at the fixed 8% width (80d is new)
and reports per-window drawdown win rate -- the metric on which the
reversal appears -- not just the aggregate Worst DD scalar, which masked it.

Pre-tax, 172 windows, same config as every other rolling table here.
Reuses strat_backtest directly; no engine changes.

Run manually:
    python backtest/trailing_stop_stability_probe.py
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

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_stability_probe_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

# Walk the pct axis at fixed 60d, then the cooldown axis at fixed 8%.
# (8%, 60d) appears once, as the shared centre of both walks.
PCT_WALK = [0.06, 0.07, 0.08, 0.09, 0.10]
PCT_WALK_COOLDOWN = 60
COOLDOWN_WALK = [40, 60, 80]
COOLDOWN_WALK_PCT = 0.08

CANDIDATE = (0.08, 60)


def build_variants():
    """[(pct, cooldown, axis)] -- baseline first, then both walks, deduped."""
    variants = [(None, None, "baseline")]
    seen = set()
    for pct in PCT_WALK:
        key = (pct, PCT_WALK_COOLDOWN)
        seen.add(key)
        variants.append((pct, PCT_WALK_COOLDOWN, "pct axis"))
    for cd in COOLDOWN_WALK:
        key = (COOLDOWN_WALK_PCT, cd)
        if key in seen:
            continue
        seen.add(key)
        variants.append((COOLDOWN_WALK_PCT, cd, "cooldown axis"))
    return variants


def build_strategies(variants):
    strategies = []
    for pct, cooldown, _ in variants:
        if pct is None:
            strategies.append(SMATrendFollowing(
                sma_window=200, atr_multiplier=2.5, t2_confirmation=True))
        else:
            strategies.append(SMATrendFollowing(
                sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                trailing_stop_pct=pct, trailing_stop_cooldown_days=cooldown))
    return strategies


if __name__ == "__main__":
    variants = build_variants()
    strategies = build_strategies(variants)
    start_dates = warmup_aware_start_dates([BASE_TICKER, SIGNAL_TICKER], PERIOD_YEARS)

    print(f"Running {len(start_dates)}-window rolling backtest for {len(strategies)} strategies...")
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)
    baseline_row = summary[0]
    baseline_dd_col = f"{strategies[0].name} Max DD (%)"

    def label_for(pct, cooldown):
        if pct is None:
            return "baseline"
        marker = "  <-- CANDIDATE" if (pct, cooldown) == CANDIDATE else ""
        return f"{pct:.0%}, {cooldown}d{marker}"

    lines = [f"### Trailing-Stop Stability Probe ({len(df_res)} windows, ^NDX/3x, S&P signal, pre-tax)", "",
             "Per-window drawdown win rate is the metric of interest: the aggregate",
             "Worst DD scalar masked the sign reversal this probe is testing for.", "",
             "| Config | Axis | Avg TWR | vs. base | DD improved | DD worsened | Identical | Mean Max DD | Avg Trades |",
             "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]

    for i, s in enumerate(summary):
        pct, cooldown, axis = variants[i]
        col = f"{strategies[i].name} Max DD (%)"
        if i == 0:
            lines.append(
                f"| baseline | -- | {s['Avg TWR']:.2f}% | -- | -- | -- | -- "
                f"| {df_res[col].mean():.2f}% | {s['Avg Trades']:.1f} |")
            continue
        # Max DD is negative; less negative = smaller drawdown = better.
        better = int((df_res[col] > df_res[baseline_dd_col]).sum())
        worse = int((df_res[col] < df_res[baseline_dd_col]).sum())
        same = int((df_res[col] == df_res[baseline_dd_col]).sum())
        delta = s["Avg TWR"] - baseline_row["Avg TWR"]
        lines.append(
            f"| {label_for(pct, cooldown)} | {axis} | {s['Avg TWR']:.2f}% | {delta:+.2f}pp "
            f"| {better} | {worse} | {same} | {df_res[col].mean():.2f}% | {s['Avg Trades']:.1f} |"
        )

    lines += ["", "**How to read this:** if `DD improved` falls off smoothly as the stop",
              "widens (e.g. 172 -> ~150 -> ~100 -> ~50 -> 4), the candidate sits on a",
              "gradient and its drawdown benefit is a real, if width-sensitive, property.",
              "If it collapses abruptly (e.g. 172 at 8% -> single digits at 9%), the",
              "candidate sits on a cliff -- the same non-monotonic signature rejected for",
              "atr_spike_multiplier and for (5%, 60d) -- and should NOT be adopted on the",
              "strength of the 172/172 result alone."]

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
