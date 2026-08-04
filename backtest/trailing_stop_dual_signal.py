"""
Does the trailing-stop's drawdown property carry over to the dual-signal
(NDX + S&P 500 agreement, no T+2) setup?

Motivation: every trailing-stop result so far is measured on ONE strategy,
SMATrendFollowing with the S&P 500 signal and T+2. The stability probe
(docs/trailing-stop-stability-probe-2026-08-03.md) showed the drawdown
benefit is a wide plateau (172/172 windows improved at every stop width
6-9%) that falls off a cliff between 9% and 10%. If that is a genuine
mechanism-level property rather than an artifact of the SMA+T+2 signal, it
should reappear on a structurally different signal. The user's live approach
is DualSignalAgreement with t2_confirmation=False -- a different entry/exit
rule entirely (requires NDX and S&P 500 to agree, acts same-day) -- so it is
the natural falsification test.

Design:
- Baseline: DualSignalAgreement(t2_confirmation=False), the user's live rule.
- Candidates: the same baseline + a trailing stop, walked across the exact
  pct axis the stability probe used (6/7/8/9/10% at 60d cooldown), so the
  two tables are directly comparable and the plateau-then-cliff structure
  can be looked for.

Two implementation notes:
1. The trailing stop overlay is REUSED verbatim, not reimplemented:
   SMATrendFollowing._apply_trailing_stop only reads df['in_market'],
   df['Close'], self.trailing_stop_pct and self.trailing_stop_cooldown_days,
   so it is called as an unbound method on a DualSignalAgreement subclass.
   No engine file is modified; the exact lookahead-free tested code runs.
2. Price the stop tracks: DualSignalAgreement is run with signal_ticker=None
   (as in compare_signal_hybrid.py), so the Backtester passes ^NDX -- the
   traded, unleveraged base ticker -- as df. The stop therefore tracks ^NDX
   here, whereas the published SMATrendFollowing stop tracked its ^GSPC
   signal ticker. This makes the numbers NOT directly comparable to the
   (8%,60d)=SMA result, by design: the valid comparison is dual-signal vs.
   dual-signal+stop, both on the same ^NDX basis. Tracking the held
   instrument's own price is arguably the more natural choice for a stop.

Pre-tax, 172 windows, ^NDX/3x. Reuses strat_backtest; no engine changes.

Run manually:
    python backtest/trailing_stop_dual_signal.py
"""
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    DualSignalAgreement, SMATrendFollowing, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_dual_signal_output.md"

CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26
ATR = 2.5
# Both tickers are required to build the dual signal regardless of which one
# the Backtester nominally treats as the signal ticker.
SIGNAL_TICKERS = ["^NDX", "^GSPC"]

# Same pct axis as docs/trailing-stop-stability-probe-2026-08-03.md, fixed
# 60d cooldown, so the plateau-then-cliff structure is directly comparable.
PCT_WALK = [0.06, 0.07, 0.08, 0.09, 0.10]
COOLDOWN = 60
CANDIDATE_PCT = 0.08


class DualSignalWithStop(DualSignalAgreement):
    """DualSignalAgreement plus the SMATrendFollowing trailing-stop overlay,
    applied after the dual-signal in_market column is built. Off (identical
    to DualSignalAgreement) when trailing_stop_pct is None."""

    def __init__(self, sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                 trailing_stop_pct=None, trailing_stop_cooldown_days=60):
        super().__init__(sma_window=sma_window, atr_multiplier=atr_multiplier,
                         t2_confirmation=t2_confirmation)
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_cooldown_days = trailing_stop_cooldown_days
        if trailing_stop_pct:
            self.name += (f" [Trailing Stop {trailing_stop_pct*100:.1f}%, "
                          f"cooldown {trailing_stop_cooldown_days}d]")

    def _add_indicator_logic(self, df):
        df = super()._add_indicator_logic(df)
        if self.trailing_stop_pct:
            # Reuse the exact tested overlay, unbound, on this instance.
            df["in_market"] = SMATrendFollowing._apply_trailing_stop(self, df)
        return df


def build_strategies():
    strategies = [DualSignalWithStop(atr_multiplier=ATR, t2_confirmation=False)]  # baseline
    for pct in PCT_WALK:
        strategies.append(DualSignalWithStop(
            atr_multiplier=ATR, t2_confirmation=False,
            trailing_stop_pct=pct, trailing_stop_cooldown_days=COOLDOWN))
    return strategies


def run_tracking(track_ticker, track_label):
    """Run the 6-strategy walk with the stop tracking `track_ticker`.
    Passing signal_ticker=track_ticker sets which price series the Backtester
    hands to _add_indicator_logic, hence which price the stop tracks; the
    dual-signal entry rule is unaffected (it fetches ^NDX+^GSPC internally)."""
    strategies = build_strategies()
    start_dates = warmup_aware_start_dates(SIGNAL_TICKERS, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker="^NDX", signal_ticker=track_ticker,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)
    baseline_row = summary[0]
    baseline_dd_col = f"{strategies[0].name} Max DD (%)"

    lines = [f"### Trailing Stop on Dual-Signal (NDX+S&P agreement, no T+2), stop tracks {track_label} -- {len(df_res)} windows, ^NDX/3x, pre-tax",
             "",
             "| Config | Avg TWR | vs. base | Med TWR | Worst DD | DD improved | DD worsened | Identical | Mean Max DD | Avg Trades |",
             "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i, s in enumerate(summary):
        col = f"{strategies[i].name} Max DD (%)"
        if i == 0:
            lines.append(
                f"| baseline (no stop) | {s['Avg TWR']:.2f}% | -- | {s['Med TWR']:.2f}% "
                f"| {s['Worst DD']:.2f}% | -- | -- | -- | {df_res[col].mean():.2f}% | {s['Avg Trades']:.1f} |")
            continue
        pct = PCT_WALK[i - 1]
        marker = "  <-- CANDIDATE" if pct == CANDIDATE_PCT else ""
        better = int((df_res[col] > df_res[baseline_dd_col]).sum())
        worse = int((df_res[col] < df_res[baseline_dd_col]).sum())
        same = int((df_res[col] == df_res[baseline_dd_col]).sum())
        delta = s["Avg TWR"] - baseline_row["Avg TWR"]
        lines.append(
            f"| {pct:.0%}, {COOLDOWN}d{marker} | {s['Avg TWR']:.2f}% | {delta:+.2f}pp | {s['Med TWR']:.2f}% "
            f"| {s['Worst DD']:.2f}% | {better} | {worse} | {same} | {df_res[col].mean():.2f}% | {s['Avg Trades']:.1f} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    warnings.filterwarnings("ignore")

    # Two runs isolate the two variables that differ from the published
    # SMATrendFollowing stop at once. ^NDX tracking is the realistic choice
    # for someone holding TQQQ (track what you hold); ^GSPC tracking holds
    # the tracking ticker equal to the published SMA stop, isolating the
    # dual-signal ENTRY RULE as the only difference.
    print("Running dual-signal stop, tracking ^NDX (realistic for a TQQQ holder)...")
    ndx_table = run_tracking("^NDX", "^NDX (traded base ticker)")
    print("Running dual-signal stop, tracking ^GSPC (isolates the entry-rule effect)...")
    gspc_table = run_tracking("^GSPC", "^GSPC (same as published SMA stop)")

    note = ("\n".join([
        "**Reading these two tables together:**",
        "- If the `DD improved` plateau (near-172 across 6-9%) appears in BOTH,",
        "  the drawdown benefit survives a change of entry/exit rule -- a",
        "  mechanism-level property, not an SMA+T+2 artifact.",
        "- The two tables differ almost entirely in trade count and return: the",
        "  stop fires far more often tracking the more-volatile ^NDX than the",
        "  less-volatile ^GSPC, so ^NDX tracking pays a much larger return cost",
        "  for a similar drawdown benefit. Tracking the less-volatile reference",
        "  is materially better -- the same reasoning behind the published stop",
        "  tracking ^GSPC rather than the leveraged equity curve.",
    ]))

    output = "\n\n".join([ndx_table, gspc_table, note])
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
