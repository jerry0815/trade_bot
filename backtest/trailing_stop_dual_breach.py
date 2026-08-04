"""
"Both must breach" dual-signal trailing stop.

The user's exit rule mirrors their entry rule: exit ONLY when BOTH ^NDX and
^GSPC have each independently breached their own trailing stop (each fallen
`pct` below its own peak-since-entry). This differs from every prior
trailing-stop test, which fired on a SINGLE ticker's breach. Requiring
agreement makes the exit strictly more conservative -- it fires later and
less often than either single-ticker stop.

Base entry rule: DualSignalAgreement, no T+2 (the user's live approach).

Comparison set, all on the same 172 windows:
  - baseline: dual-signal, no stop
  - dual-breach stop: the new "both must breach" overlay, width walk 6-10%
  - for reference, the two single-ticker stops from
    docs/trailing-stop-dual-signal-2026-08-03.md at 8% are re-run here so
    all three exit rules sit in one table.

Implementation: a new _apply_dual_trailing_stop overlay, written in this
script (NOT an engine change), mirroring the tested single-ticker
_apply_trailing_stop loop exactly -- same lag convention (close[i-1]), same
fresh-entry peak seeding, same trend-exit-wins precedence, same
cooldown-after-stop -- but tracking two peaks and requiring BOTH breached.
The single-ticker reference rows reuse SMATrendFollowing._apply_trailing_stop
verbatim (unbound), as in trailing_stop_dual_signal.py.

Pre-tax, 172 windows, ^NDX/3x. Run manually:
    python backtest/trailing_stop_dual_breach.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    DualSignalAgreement, SMATrendFollowing, get_cached_signals,
    run_experiment_suite, warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_dual_breach_output.md"

CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26
ATR = 2.5
SIGNAL_TICKERS = ["^NDX", "^GSPC"]
PCT_WALK = [0.06, 0.07, 0.08, 0.09, 0.10]
COOLDOWN = 60
CANDIDATE_PCT = 0.08


def _dual_breach_in_market(trend_in_market, ndx_lagged, gspc_lagged, pct, cooldown_days):
    """Both-must-breach overlay. Exit only when BOTH lagged closes are below
    their own peak-since-entry * (1 - pct). Mirrors _apply_trailing_stop's
    structure (trend exit wins first and starts no cooldown; only a joint
    stop breach starts the cooldown)."""
    n = len(trend_in_market)
    final = np.zeros(n, dtype=bool)
    was_in = False
    peak_n = 0.0
    peak_g = 0.0
    cooldown = 0
    for i in range(n):
        if cooldown > 0:
            final[i] = False
            cooldown -= 1
            was_in = False
            continue
        if not trend_in_market[i]:
            final[i] = False
            was_in = False
            continue
        if not was_in:
            peak_n = ndx_lagged[i]
            peak_g = gspc_lagged[i]
            was_in = True
            final[i] = True
            continue
        peak_n = max(peak_n, ndx_lagged[i])
        peak_g = max(peak_g, gspc_lagged[i])
        breach_n = ndx_lagged[i] < peak_n * (1 - pct)
        breach_g = gspc_lagged[i] < peak_g * (1 - pct)
        if breach_n and breach_g:
            final[i] = False
            was_in = False
            cooldown = cooldown_days
        else:
            final[i] = True
    return final


class DualSignalDualBreachStop(DualSignalAgreement):
    """Dual-signal entry + both-must-breach trailing-stop exit."""

    def __init__(self, trailing_stop_pct=None, trailing_stop_cooldown_days=60, **kw):
        super().__init__(**kw)
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_cooldown_days = trailing_stop_cooldown_days
        if trailing_stop_pct:
            self.name += (f" [Dual-Breach Stop {trailing_stop_pct*100:.1f}%, "
                          f"cooldown {trailing_stop_cooldown_days}d]")

    def _add_indicator_logic(self, df):
        df = super()._add_indicator_logic(df)
        if not self.trailing_stop_pct:
            return df
        ndx = get_cached_signals("^NDX")["Close"].reindex(df.index).ffill().to_numpy()
        gspc = get_cached_signals("^GSPC")["Close"].reindex(df.index).ffill().to_numpy()
        ndx_lag = np.roll(ndx, 1)
        gspc_lag = np.roll(gspc, 1)
        if len(df):
            ndx_lag[0] = ndx[0]
            gspc_lag[0] = gspc[0]
        final = _dual_breach_in_market(
            df["in_market"].to_numpy(), ndx_lag, gspc_lag,
            self.trailing_stop_pct, self.trailing_stop_cooldown_days)
        df["in_market"] = pd.Series(final, index=df.index)
        return df


class DualSignalSingleStop(DualSignalAgreement):
    """Reference: dual-signal entry + single-ticker stop (reuses the tested
    overlay). signal_ticker chosen at Backtester level decides which price
    df['Close'] carries, hence which ticker this tracks."""

    def __init__(self, trailing_stop_pct=None, trailing_stop_cooldown_days=60, tag="", **kw):
        super().__init__(**kw)
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_cooldown_days = trailing_stop_cooldown_days
        if trailing_stop_pct:
            self.name += f" [Single Stop {trailing_stop_pct*100:.1f}% {tag}]"

    def _add_indicator_logic(self, df):
        df = super()._add_indicator_logic(df)
        if self.trailing_stop_pct:
            df["in_market"] = SMATrendFollowing._apply_trailing_stop(self, df)
        return df


def run_and_rows(strategies, track_ticker):
    start_dates = warmup_aware_start_dates(SIGNAL_TICKERS, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker="^NDX", signal_ticker=track_ticker,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)
    return df_res, summary


def fmt_row(label, s, df_res, col, baseline_dd_col, baseline_twr):
    if baseline_dd_col is None:
        return (f"| {label} | {s['Avg TWR']:.2f}% | -- | {s['Med TWR']:.2f}% "
                f"| {s['Worst DD']:.2f}% | -- | {df_res[col].mean():.2f}% | {s['Avg Trades']:.1f} |")
    better = int((df_res[col] > df_res[baseline_dd_col]).sum())
    delta = s["Avg TWR"] - baseline_twr
    return (f"| {label} | {s['Avg TWR']:.2f}% | {delta:+.2f}pp | {s['Med TWR']:.2f}% "
            f"| {s['Worst DD']:.2f}% | {better}/172 | {df_res[col].mean():.2f}% | {s['Avg Trades']:.1f} |")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")

    # --- Main run: both-must-breach stop across the width walk (tracks both
    # tickers internally, so signal_ticker is irrelevant to the stop; use
    # None so df is ^NDX for a stable index). ---
    strategies = [DualSignalDualBreachStop(atr_multiplier=ATR, t2_confirmation=False)]
    for pct in PCT_WALK:
        strategies.append(DualSignalDualBreachStop(
            atr_multiplier=ATR, t2_confirmation=False,
            trailing_stop_pct=pct, trailing_stop_cooldown_days=COOLDOWN))
    print("Running both-must-breach dual stop, width walk...")
    df_res, summary = run_and_rows(strategies, None)
    baseline_twr = summary[0]["Avg TWR"]
    baseline_dd_col = f"{strategies[0].name} Max DD (%)"

    lines = [f"### Both-Must-Breach Dual Trailing Stop on Dual-Signal (no T+2) -- 172 windows, ^NDX/3x, pre-tax",
             "",
             "Exit only when BOTH ^NDX and ^GSPC breach their own trailing stop.",
             "", "| Config | Avg TWR | vs. base | Med TWR | Worst DD | DD improved | Mean Max DD | Avg Trades |",
             "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i, s in enumerate(summary):
        col = f"{strategies[i].name} Max DD (%)"
        if i == 0:
            lines.append(fmt_row("baseline (no stop)", s, df_res, col, None, None))
            continue
        pct = PCT_WALK[i - 1]
        marker = "  <-- CANDIDATE" if pct == CANDIDATE_PCT else ""
        lines.append(fmt_row(f"{pct:.0%}, {COOLDOWN}d{marker}", s, df_res, col, baseline_dd_col, baseline_twr))

    # --- Reference: the three exit rules head-to-head at the 8% candidate. ---
    dual8 = [DualSignalDualBreachStop(atr_multiplier=ATR, t2_confirmation=False),
             DualSignalDualBreachStop(atr_multiplier=ATR, t2_confirmation=False,
                                      trailing_stop_pct=CANDIDATE_PCT, trailing_stop_cooldown_days=COOLDOWN)]
    df_d, sum_d = run_and_rows(dual8, None)

    print("Running single-ticker reference stops at 8% (NDX-tracked, GSPC-tracked)...")
    single_ndx = [DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False),
                  DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False, tag="NDX",
                                       trailing_stop_pct=CANDIDATE_PCT, trailing_stop_cooldown_days=COOLDOWN)]
    df_n, sum_n = run_and_rows(single_ndx, "^NDX")
    single_gspc = [DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False),
                   DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False, tag="GSPC",
                                        trailing_stop_pct=CANDIDATE_PCT, trailing_stop_cooldown_days=COOLDOWN)]
    df_g, sum_g = run_and_rows(single_gspc, "^GSPC")

    b_twr = sum_d[0]["Avg TWR"]
    lines += ["", "### Exit-rule comparison at 8%, 60d (same dual-signal entry)", "",
              "| Exit rule | Avg TWR | vs. base | Worst DD | DD improved | Mean Max DD | Avg Trades |",
              "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]

    def add_ref(label, df_r, summ, strategies_list):
        s = summ[1]
        col = f"{strategies_list[1].name} Max DD (%)"
        bcol = f"{strategies_list[0].name} Max DD (%)"
        better = int((df_r[col] > df_r[bcol]).sum())
        delta = s["Avg TWR"] - summ[0]["Avg TWR"]
        lines.append(f"| {label} | {s['Avg TWR']:.2f}% | {delta:+.2f}pp | {s['Worst DD']:.2f}% "
                     f"| {better}/172 | {df_r[col].mean():.2f}% | {s['Avg Trades']:.1f} |")

    add_ref("both must breach (NDX & GSPC)", df_d, sum_d, dual8)
    add_ref("single: NDX only", df_n, sum_n, single_ndx)
    add_ref("single: GSPC only", df_g, sum_g, single_gspc)

    lines += ["",
              "**Both-must-breach fires later and less often than either single stop.**",
              "Whether that is better depends on which column you weight: fewer trades",
              "and less return drag, but a more conservative exit reaches a deeper",
              "drawdown before acting -- read the `Mean Max DD` and `Avg Trades`",
              "columns together."]

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
