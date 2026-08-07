"""
Per-strategy drawdown across the 5 known crash events, as one
strategies x events table.

Reuses the event-relative decline methodology already established in
backtest/trailing_stop_sweep.py and backtest/event_leverage_comparison.py:
each event's drawdown is the peak-to-trough decline measured from the equity
value at/just-before the event's well-known start date to the local trough
within the event window (^NDX/3x, S&P-signal-driven, 40-year run from
1986-04-29). EVENTS, event_decline, and get_equity_curve are imported from
trailing_stop_sweep rather than redefined.

Strategies compared (the same A/B/C/D from
docs/combined-system-comparison-2026-08-03.md, plus Buy & Hold as the
crash-severity floor):
  Buy & Hold (3x)                -- no trend exit at all
  A  SMA + T+2 (live baseline)
  B  A + ^GSPC trailing stop 8/60
  C  Dual-signal agreement, no T+2
  D  C + ^GSPC trailing stop 8/60

Run manually:
    python backtest/crash_event_drawdown.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing, DualSignalAgreement, BuyAndHold
from backtest.trailing_stop_sweep import EVENTS, event_decline, get_equity_curve

OUTPUT_PATH = REPO_ROOT / "backtest" / "crash_event_drawdown_output.md"

STOP_PCT = 0.08
STOP_COOLDOWN = 60


def build_strategies():
    return [
        ("Buy & Hold (3x)", BuyAndHold()),
        ("A: SMA + T+2 (baseline)",
         SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)),
        ("B: SMA + T+2 + GSPC stop 8/60",
         SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                           trailing_stop_pct=STOP_PCT, trailing_stop_cooldown_days=STOP_COOLDOWN)),
        ("C: Dual-signal (no T+2)",
         DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False)),
        ("D: Dual-signal + GSPC stop 8/60",
         DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                             trailing_stop_pct=STOP_PCT, trailing_stop_cooldown_days=STOP_COOLDOWN)),
        ("E: Dual-signal + GSPC velocity 6%/60d rolling_max",
         DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                             velocity_stop_pct=0.06, velocity_stop_window=60,
                             velocity_stop_mode="rolling_max", velocity_stop_cooldown_days=60)),
        ("F: Dual-signal + GSPC velocity 6%/30d point_to_point",
         DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                             velocity_stop_pct=0.06, velocity_stop_window=30,
                             velocity_stop_mode="point_to_point", velocity_stop_cooldown_days=60)),
    ]


if __name__ == "__main__":
    strategies = build_strategies()
    event_names = [name for name, _s, _e in EVENTS]

    # {strategy_label: {event_name: decline_pct or None}}
    results = {}
    for label, strat in strategies:
        print(f"Running {label}...")
        eq = get_equity_curve(strat)
        row = {}
        for event_name, start, end in EVENTS:
            row[event_name] = event_decline(eq, start, end) if eq is not None else None
        results[label] = row

    header = "| Strategy | " + " | ".join(event_names) + " |"
    sep = "| :--- | " + " | ".join(["---:"] * len(event_names)) + " |"
    lines = ["### Per-Strategy Drawdown by Crash Event (^NDX/3x, S&P signal, event-relative peak-to-trough)",
             "",
             "Each cell is the equity decline from just before the event to the "
             "trough within the event window. Less negative = better protected.",
             "",
             header, sep]
    for label, _strat in strategies:
        cells = []
        for event_name in event_names:
            v = results[label][event_name]
            cells.append("n/a" if v is None else f"{v:.2f}%")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    output = "\n".join(lines)
    print("\n" + output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
