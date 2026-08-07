"""
Selection + evaluation sweep for the fixed-window ("velocity") trailing stop
vs the existing peak-based stop. Selection phase reuses trailing_stop_sweep's
single-run event-relative decline (^NDX/3x, S&P signal); evaluation phase
runs the chosen variant(s) through the full rolling Table-4 comparison.

Run manually:
    python backtest/velocity_stop_sweep.py

Writes a markdown report to stdout AND backtest/velocity_stop_sweep_output.md.
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, DualSignalAgreement, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)
from backtest.trailing_stop_sweep import EVENTS, event_decline, get_equity_curve

OUTPUT_PATH = REPO_ROOT / "backtest" / "velocity_stop_sweep_output.md"

MODES = ["rolling_max", "point_to_point"]
WINDOW_GRID = [20, 30, 60]
PCT_GRID = [0.06, 0.08, 0.10, 0.12]
COOLDOWN_GRID = [20, 40, 60]
PERIOD_YEARS = 26
LEVERAGE_CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR = 2.5


# ---------------------------------------------------------------------------
# Selection phase: 72-variant single-run event-relative decline (mirrors
# trailing_stop_sweep.py), ^NDX/3x with S&P-signal SMATrendFollowing.
# ---------------------------------------------------------------------------
def selection_phase():
    baseline = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    eq_base = get_equity_curve(baseline)
    base_declines = {name: event_decline(eq_base, s, e) for name, s, e in EVENTS}

    rows = []
    for mode in MODES:
        for window in WINDOW_GRID:
            for pct in PCT_GRID:
                for cooldown in COOLDOWN_GRID:
                    strat = SMATrendFollowing(
                        sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                        velocity_stop_pct=pct, velocity_stop_window=window,
                        velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown,
                    )
                    print(f"Running {mode} pct={pct:.0%} window={window}d cooldown={cooldown}d...")
                    eq = get_equity_curve(strat)
                    if eq is None:
                        continue
                    improvements = []
                    per_event = {}
                    for name, s, e in EVENTS:
                        sd = event_decline(eq, s, e)
                        bd = base_declines[name]
                        per_event[name] = sd
                        if sd is not None and bd is not None:
                            improvements.append(sd - bd)
                    rows.append({
                        "mode": mode, "window": window, "pct": pct, "cooldown": cooldown,
                        "avg_improvement": sum(improvements) / len(improvements) if improvements else float("nan"),
                        "per_event": per_event,
                    })
    return base_declines, rows


def render_selection_tables(base_declines, rows):
    event_names = [name for name, _, _ in EVENTS]

    df = pd.DataFrame(rows).sort_values("avg_improvement", ascending=False).reset_index(drop=True)

    lines = ["### Velocity-Stop Selection: Event-Relative Decline vs Baseline (^NDX/3x, S&P signal, T+2)", ""]
    lines.append("Baseline (no stop) event declines: " +
                  ", ".join(f"{n} {base_declines[n]:.2f}%" for n in event_names))
    lines.append("")

    header = ["Mode", "Window", "Pct", "Cooldown"] + event_names + ["Avg Improvement (pp)"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for _, r in df.iterrows():
        cells = [r["mode"], f"{r['window']:.0f}d", f"{r['pct']:.0%}", f"{r['cooldown']:.0f}d"]
        for n in event_names:
            v = r["per_event"].get(n)
            cells.append(f"{v:.2f}%" if v is not None else "N/A")
        cells.append(f"{r['avg_improvement']:+.2f}")
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")

    lines.append("")
    lines.append("Ranked full-grid table above (sorted by Avg Improvement, best first, 72 variants).")
    lines.append("")

    selected = {}
    for mode in MODES:
        mode_rows = df[df["mode"] == mode]
        if mode_rows.empty:
            continue
        best = mode_rows.loc[mode_rows["avg_improvement"].idxmax()]
        selected[mode] = best
        line = (f"SELECTED VELOCITY VARIANT ({mode}): pct={best['pct']:.0%}, "
                f"window={best['window']:.0f}, cooldown={best['cooldown']:.0f}")
        print(line)
        lines.append(line)

    return "\n".join(lines), selected


# ---------------------------------------------------------------------------
# Evaluation phase: rolling Table-4-style comparison of the chosen variant(s)
# on both carriers, plus the no-stop and peak-8%/60d anchors.
# ---------------------------------------------------------------------------
def rolling_row(label, strat):
    tickers = ["^NDX", "^GSPC"]
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[LEVERAGE_CONFIG], strategies=[strat], start_dates=start_dates,
        period_years=PERIOD_YEARS, annual_dca=0, base_ticker="^NDX",
        signal_ticker=("^GSPC" if isinstance(strat, SMATrendFollowing) else None),
        initial_fund=10000, apply_tax=False, print_summary=False,
    )
    df_res = results[LEVERAGE_CONFIG["name"]]
    print(f"  {label}: {len(df_res)}/{len(start_dates)} candidate windows accepted")
    summary = summarize_rolling_results(df_res, [strat], metric_label="TWR")
    if not summary:
        return None
    r = dict(summary[0]); r["Label"] = label; r["n_windows"] = len(df_res)
    return r


def build_evaluation_setups(selected):
    setups = [
        ("Dual-signal agreement (no stop)",
         DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False)),
        ("Dual-signal agreement + Trailing Stop 8%/60d (peak anchor)",
         DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False,
                              trailing_stop_pct=0.08, trailing_stop_cooldown_days=60)),
    ]
    for mode, best in selected.items():
        pct, window, cooldown = best["pct"], int(best["window"]), int(best["cooldown"])
        label_suffix = f"{mode} {pct:.0%}/{window}d, cooldown {cooldown}d"
        setups.append((
            f"S&P 500 signal [T+2] + Velocity Stop {label_suffix}",
            SMATrendFollowing(sma_window=200, atr_multiplier=ATR, t2_confirmation=True,
                               velocity_stop_pct=pct, velocity_stop_window=window,
                               velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown),
        ))
        setups.append((
            f"Dual-signal agreement + Velocity Stop {label_suffix}",
            DualSignalAgreement(sma_window=200, atr_multiplier=ATR, t2_confirmation=False,
                                 velocity_stop_pct=pct, velocity_stop_window=window,
                                 velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown),
        ))
    return setups


def render_evaluation_table(rows):
    lines = [
        "### Velocity-Stop Rolling Evaluation (^NDX/3x, ATR x2.5, 26yr rolling windows)",
        "",
        "| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades | Windows |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['Label']} | {r['Avg TWR']:.2f}% | {r['Med TWR']:.2f}% | {r['Worst TWR']:.2f}% "
            f"| {r['Worst DD']:.2f}% | {r['Avg Trades']:.0f} | {r['n_windows']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Selection phase ===")
    base_declines, sel_rows = selection_phase()
    selection_md, selected = render_selection_tables(base_declines, sel_rows)
    print("\n" + selection_md)

    print("\n=== Evaluation phase ===")
    eval_setups = build_evaluation_setups(selected)
    eval_rows = []
    for label, strat in eval_setups:
        row = rolling_row(label, strat)
        if row:
            eval_rows.append(row)
    evaluation_md = render_evaluation_table(eval_rows)
    print("\n" + evaluation_md)

    output = selection_md + "\n\n---\n\n" + evaluation_md + "\n"
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
