"""Runs the production recommendation under a real accumulation schedule:
$10,000 initial + $2,000 contributed at the end of every month.

Two production configs (the README "Final Decision" pair), 3x ^NDX, S&P signal:
  C  Dual-signal agreement, no stop        -- taxable-account pick
  D  C + GSPC trailing stop (8%, 60d)       -- tax-advantaged pick

Purpose: show what monthly DCA changes and what it does NOT.
  - TWR ranking is cash-flow-invariant, so it must be IDENTICAL to lump sum.
    We run both lump-sum and monthly-DCA and print them side by side to prove
    the strategy CHOICE does not change.
  - Dollar outcome / money-weighted ROI / worst-case drawdown DO change; those
    are reported from the DCA run.

Reuses DualSignalSingleStop from trailing_stop_dual_breach.py. Engine gains a
monthly_dca knob (Backtester(monthly_dca=...)); no strategy-logic change.

Run manually:
    python backtest/monthly_dca_comparison.py
"""
import sys
import warnings
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import run_experiment_suite, warmup_aware_start_dates
from backtest.trailing_stop_dual_breach import DualSignalSingleStop

OUTPUT_PATH = REPO_ROOT / "backtest" / "monthly_dca_comparison_output.md"

CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26
ATR = 2.5
STOP_PCT = 0.08
STOP_COOLDOWN = 60
INITIAL_FUND = 10000
MONTHLY_DCA = 2000


def make_strategies():
    C = DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False)
    D = DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False, tag="GSPC",
                             trailing_stop_pct=STOP_PCT,
                             trailing_stop_cooldown_days=STOP_COOLDOWN)
    return [("C", "Dual-signal, no stop (taxable pick)", C),
            ("D", "Dual-signal + stop 8/60 (tax-adv pick)", D)]


def run_suite(strategies, monthly_dca, apply_tax=False):
    start_dates = warmup_aware_start_dates(["^NDX", "^GSPC"], PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker="^NDX", signal_ticker="^GSPC",
        monthly_dca=monthly_dca, initial_fund=INITIAL_FUND,
        apply_tax=apply_tax, print_summary=False,
    )
    return results[CONFIG["name"]], len(start_dates)


def col(df, strat, suffix):
    return df[f"{strat.name} {suffix}"]


def main():
    warnings.filterwarnings("ignore")
    labelled = make_strategies()
    strategies = [s for _, _, s in labelled]

    print("Running 172-window rolling aggregate — LUMP SUM (control)...")
    df_lump, n_windows = run_suite(strategies, monthly_dca=0)
    print("Running 172-window rolling aggregate — $2,000/month DCA...")
    df_dca, _ = run_suite(strategies, monthly_dca=MONTHLY_DCA)
    n = len(df_dca)

    # 1) Invariance proof: TWR must match between lump-sum and DCA.
    inv = ["### 1. Strategy ranking is unchanged (TWR is cash-flow-invariant)", "",
           f"*{n} rolling 26-year windows, 3x ^NDX, S&P signal, pre-tax. "
           "Avg TWR compared: lump sum vs $2,000/mo DCA — identical by construction "
           "(TWR strips cash flows), which is why the strategy CHOICE does not change.*", "",
           "| Cfg | Strategy | Avg TWR (lump) | Avg TWR (DCA) | Max abs diff |",
           "| :-- | :--- | ---: | ---: | ---: |"]
    for key, label, strat in labelled:
        tl = col(df_lump, strat, "TWR (%)")
        td = col(df_dca, strat, "TWR (%)")
        max_diff = (tl.reset_index(drop=True) - td.reset_index(drop=True)).abs().max()
        inv.append(f"| {key} | {label} | {tl.mean():.2f}% | {td.mean():.2f}% | {max_diff:.2e} pp |")

    # 2) Dollar picture under DCA — the metrics that DO move.
    invested = INITIAL_FUND + MONTHLY_DCA * (PERIOD_YEARS * 12 - 1)
    dollars = ["### 2. Dollar outcome under $10,000 + $2,000/month", "",
               f"*Same {n} windows. Each window contributes ${INITIAL_FUND:,} up front then "
               f"${MONTHLY_DCA:,}/mo for 26 years (~${invested:,} invested per window). "
               "Final Value / ROI are money-weighted; Worst DD is peak-to-trough on the "
               "growing balance.*", "",
               "| Cfg | Strategy | Median Final Value | Avg Final Value | Median ROI | Worst DD | Avg Trades |",
               "| :-- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for key, label, strat in labelled:
        fv = col(df_dca, strat, "Final Value")
        roi = col(df_dca, strat, "Total ROI (%)")
        dd = col(df_dca, strat, "Max DD (%)")
        trades = col(df_dca, strat, "Total Trades")
        dollars.append(
            f"| {key} | {label} | ${fv.median():,.0f} | ${fv.mean():,.0f} "
            f"| {roi.median():.0f}% | {dd.min():.2f}% | {trades.mean():.1f} |"
        )

    # 3) The stop-or-not decision, in both tax regimes, under DCA:
    #    tax-advantaged account -> read the pre-tax rows (no tax on trades);
    #    taxable account -> read the after-tax rows ($24k/yr exceeds IRA/401k
    #    room, so most contributions land in a taxable account).
    print("Running 172-window rolling aggregate — C & D AFTER-TAX, $2,000/month DCA...")
    df_cd_tax, _ = run_suite(strategies, monthly_dca=MONTHLY_DCA, apply_tax=True)

    def summarize(df, strat):
        return (col(df, strat, "TWR (%)").mean(),
                col(df, strat, "Final Value").median(),
                col(df, strat, "Total ROI (%)").median(),
                col(df, strat, "Max DD (%)").min())

    aftertax = ["### 3. Stop or no stop, by tax regime, under $2,000/month DCA", "",
                f"*Same {n} windows. Tax-advantaged account -> read pre-tax rows; taxable "
                "account -> read after-tax rows. C = no stop, D = + trailing stop 8/60. "
                "Tax realised on exits; contributions correctly added to cost basis.*", "",
                "| Regime | Cfg | Avg TWR | Median Final Value | Median ROI | Worst DD |",
                "| :--- | :-- | ---: | ---: | ---: | ---: |"]
    for regime, df in [("Pre-tax (tax-adv)", df_dca), ("After-tax (taxable)", df_cd_tax)]:
        for key, label, strat in labelled:
            a = summarize(df, strat)
            aftertax.append(
                f"| {regime} | {key} | {a[0]:.2f}% | ${a[1]:,.0f} | {a[2]:.0f}% | {a[3]:.2f}% |")

    note = ["**How to read this:**",
            "- Table 1: DCA does not change *which* config wins — Avg TWR is identical "
            "to lump sum (max per-window diff is floating-point dust). The best-practice "
            "config is the same: dual-signal (C) taxable, dual-signal + stop (D) tax-advantaged.",
            "- Table 2: what DCA *does* change — the accumulated dollars and the "
            "money-weighted ROI, plus a worst-case drawdown now measured on a much larger "
            "late-period balance. The stop (D) trades a little ROI for a shallower Worst DD, "
            "same tradeoff as lump sum.",
            "- Worst DD is still a deep number: leverage, not the contribution schedule, "
            "sets the drawdown depth. DCA cushions the *early* years (cheap accumulation) "
            "but does not shrink the percentage crash on the balance you have built."]

    output = ("\n".join(inv) + "\n\n" + "\n".join(dollars) + "\n\n"
              + "\n".join(aftertax) + "\n\n" + "\n".join(note))
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
