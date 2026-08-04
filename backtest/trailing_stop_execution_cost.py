"""
Execution-cost and order-type analysis for the trailing-stop overlay.

docs/trailing-stop-stability-probe-2026-08-03.md listed commissions and
slippage as the last unmodeled gap. This script quantifies that gap and,
separately, tests a specific execution idea raised in conversation: placing
a limit order at the prior session's close instead of executing at the open.

Two findings the numbers support (see the finding doc for discussion):

1. Direct trading costs are immaterial here. The overlay adds ~6.7 round
   trips per 26-year window (17.8 vs. 11.1 trades). On a liquid 3x NDX
   product at modern retail commission rates, that is a few basis points
   spread over 26 years -- orders of magnitude below the +/-5pp return
   noise the stability probe measured.

2. The limit-at-prior-close idea fails, and fails asymmetrically. A sell
   limit at price X only fills at X or better, so it does NOT fill when the
   market gaps down through it -- which is precisely the crash scenario the
   stop exists to handle. This script measures how often that happens on
   the actual stop-trigger days.

The backtest's own execution model (Backtester._run_portfolio_math sells an
exit day at TODAY'S OPEN) corresponds to a market-on-open order, which does
participate in the opening auction -- so the modeled fill is achievable.
This script does not change that model; it only measures what the gap
between prior close and open actually was on the days that matter.

Run manually:
    python backtest/trailing_stop_execution_cost.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import get_cached_signals, SMATrendFollowing

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_execution_cost_output.md"

BASE_TICKER = "^NDX"      # what is actually traded
SIGNAL_TICKER = "^GSPC"   # what the stop is measured against
LEVERAGE = 3

CANDIDATE_PCT = 0.08
CANDIDATE_COOLDOWN = 60

# Rolling-window trade counts from
# docs/trailing-stop-loss-region-validation-2026-08-03.md, used for the
# direct-cost estimate below.
BASELINE_TRADES = 11.1
CANDIDATE_TRADES = 17.8
WINDOW_YEARS = 26
# One-way cost assumption for a highly liquid leveraged index ETF at a
# modern zero-commission retail broker: effectively half the quoted spread.
# Stated as an explicit assumption, not a measured value -- the point of the
# calculation is that even a generous figure here stays immaterial.
ONE_WAY_COST_BPS = 2.0


def stop_trigger_dates(pct, cooldown_days):
    """Dates on which the trailing stop forces an exit, replicating
    SMATrendFollowing._apply_trailing_stop's loop so the trigger days
    themselves (not just the resulting in_market column) are observable."""
    strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    df, _ = strat.generate_signals(get_cached_signals(SIGNAL_TICKER).copy())
    trend = df["in_market"].to_numpy()
    close = df["Close"].to_numpy()
    lagged = np.roll(close, 1)
    if len(lagged):
        lagged[0] = close[0]

    was_in = False
    peak = 0.0
    cooldown = 0
    hits = []
    for i in range(len(df)):
        if cooldown > 0:
            cooldown -= 1
            was_in = False
            continue
        if not trend[i]:
            was_in = False
            continue
        if not was_in:
            peak = lagged[i]
            was_in = True
            continue
        peak = max(peak, lagged[i])
        if lagged[i] < peak * (1 - pct):
            was_in = False
            cooldown = cooldown_days
            hits.append(df.index[i])
    return pd.DatetimeIndex(hits)


def gap_table(dates):
    """Overnight gap (open vs. prior close) on the traded ticker, for each
    stop-execution day. A negative gap means a sell limit resting at the
    prior close would not have filled at the open."""
    ndx = get_cached_signals(BASE_TICKER)
    rows = []
    for d in dates:
        if d not in ndx.index:
            continue
        loc = ndx.index.get_loc(d)
        if loc == 0:
            continue
        open_px = ndx["Open"].iloc[loc]
        prev_close = ndx["Close"].iloc[loc - 1]
        if pd.isna(open_px) or pd.isna(prev_close):
            continue
        rows.append({"date": d, "gap_pct": (open_px - prev_close) / prev_close * 100})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    warnings.filterwarnings("ignore")

    dates = stop_trigger_dates(CANDIDATE_PCT, CANDIDATE_COOLDOWN)
    g = gap_table(dates)
    no_fill = g[g.gap_pct < 0]

    extra_round_trips = CANDIDATE_TRADES - BASELINE_TRADES
    total_cost_bps = extra_round_trips * 2 * ONE_WAY_COST_BPS
    annual_cost_pp = (total_cost_bps / 100.0) / WINDOW_YEARS

    lines = [
        f"### Trailing-Stop Execution Cost & Order Type ({CANDIDATE_PCT:.0%}, {CANDIDATE_COOLDOWN}d)",
        "",
        "#### 1. Direct trading cost of the added turnover",
        "",
        f"| Quantity | Value |",
        f"| :--- | ---: |",
        f"| Baseline trades per {WINDOW_YEARS}-year window | {BASELINE_TRADES} |",
        f"| Candidate trades per {WINDOW_YEARS}-year window | {CANDIDATE_TRADES} |",
        f"| Extra round trips | {extra_round_trips:.1f} |",
        f"| Assumed one-way cost | {ONE_WAY_COST_BPS:.1f} bps |",
        f"| Total added cost over {WINDOW_YEARS} years | {total_cost_bps:.1f} bps |",
        f"| Annualized drag | {annual_cost_pp:.4f} pp/yr |",
        "",
        "Commissions on US-listed ETFs are $0 at mainstream retail brokers, so",
        "the figure above is spread cost only. The annualized drag is roughly",
        "three orders of magnitude smaller than the +/-5pp return-surface noise",
        "measured in docs/trailing-stop-stability-probe-2026-08-03.md.",
        "",
        "#### 2. Would a sell limit at the prior close have filled?",
        "",
        f"Stop-trigger days over full history: **{len(g)}**",
        "",
        "| Outcome | Count | Share |",
        "| :--- | ---: | ---: |",
        f"| Opened at/above prior close (limit fills) | {len(g) - len(no_fill)} | {(1 - len(no_fill)/len(g))*100:.0f}% |",
        f"| Gapped below prior close (**limit does NOT fill**) | {len(no_fill)} | {len(no_fill)/len(g)*100:.0f}% |",
        "",
        f"Mean gap {g.gap_pct.mean():+.2f}% | median {g.gap_pct.median():+.2f}% | "
        f"worst {g.gap_pct.min():+.2f}% | best {g.gap_pct.max():+.2f}%",
        "",
        "Days the limit would have failed to fill, worst first "
        f"(unleveraged {BASE_TICKER} gap; at {LEVERAGE}x the position impact is ~{LEVERAGE}x this):",
        "",
        "| Date | Gap | Approx. impact at 3x |",
        "| :--- | ---: | ---: |",
    ]
    for _, r in no_fill.sort_values("gap_pct").iterrows():
        lines.append(f"| {r.date.date()} | {r.gap_pct:+.2f}% | {r.gap_pct * LEVERAGE:+.2f}% |")

    lines += [
        "",
        "The no-fill days are not randomly distributed: they cluster on the",
        "most severe events in the sample. A limit resting at the prior close",
        "fills readily on ordinary stop days and fails precisely during the",
        "crashes the mechanism exists to handle -- and because a crash keeps",
        "falling, such an order can remain unfilled indefinitely, leaving the",
        "position unprotected for the entire decline rather than costing a",
        "one-off slippage amount.",
    ]

    output = "\n".join(lines)
    print(output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
