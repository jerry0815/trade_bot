"""26-year rolling backtest over the options-overlay engine.

Mirrors the repo's rolling methodology (`docs/strategies/methodology.md`): step a
26-year window forward and report the distribution of annualized returns and the
worst drawdowns across windows, rather than a single lucky path. This makes the
overlay results directly comparable to the rest of the repo's tables.

    python -m options.rolling_benchmark                 # 1990-2026, quarterly step
    python -m options.rolling_benchmark --step-months 1 # monthly (slower)

Requires network (yfinance) via ``reconstruct_tqqq.prepare_extended_data``.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .overlay_backtest import run_model, OverlayConfig, OptionsOverlayBacktester

MODELS = ["buy_hold", "trend", "static_cc", "collar"]
MODEL_LABELS = {
    "buy_hold": "Buy & Hold TQQQ",
    "trend": "Trend (no options)",
    "static_cc": "Covered Calls",
    "collar": "Collar (P.15)",
}


def _run(model: str, window: pd.DataFrame):
    if model == "collar":
        return OptionsOverlayBacktester(OverlayConfig(model="collar", collar_put_delta=0.15)).run(window)
    return run_model(window, model)


def window_starts(index: pd.DatetimeIndex, years: int, step_months: int) -> list[pd.Timestamp]:
    """Every ``step_months``-spaced start whose ``years``-long window fits the data."""
    starts, k = [], 0
    while True:
        s = index[0] + pd.DateOffset(months=step_months * k)
        if s + pd.DateOffset(years=years) > index[-1]:
            break
        starts.append(s)
        k += 1
    return starts


def run_rolling(data: pd.DataFrame, models=MODELS, years: int = 26,
                step_months: int = 3, min_days: int = 252 * 20) -> dict:
    """Aggregate per-window CAGR + drawdowns across rolling windows, per model."""
    starts = window_starts(data.index, years, step_months)
    agg = {m: {"cagr": [], "dd": [], "ddinit": [], "trades": []} for m in models}
    for s in starts:
        w = data.loc[s: s + pd.DateOffset(years=years)]
        if len(w) < min_days:
            continue
        for m in models:
            res = _run(m, w)
            k = res.kpis
            vals = res.equity_curve.values.astype(float)
            agg[m]["cagr"].append(k["CAGR (%)"])
            agg[m]["dd"].append(k["Max Drawdown (MDD %)"])
            agg[m]["ddinit"].append((vals.min() / k["Initial Capital ($)"] - 1) * 100)
            agg[m]["trades"].append(k["Total Option Trades"])
    agg["_starts"] = starts
    return agg


def format_table(agg: dict, models=MODELS) -> str:
    rows = [
        "| Model | Avg CAGR | Med CAGR | Worst CAGR | Worst DD | Worst DDvInit |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for m in models:
        a = agg[m]
        rows.append(
            f"| {MODEL_LABELS[m]} | {np.mean(a['cagr']):.1f}% | {np.median(a['cagr']):.1f}% | "
            f"{np.min(a['cagr']):.1f}% | {np.min(a['dd']):.1f}% | {np.min(a['ddinit']):.1f}% |"
        )
    return "\n".join(rows)


def main(argv=None):  # pragma: no cover - network + long-running
    from .reconstruct_tqqq import prepare_extended_data

    ap = argparse.ArgumentParser(description="26-year rolling options-overlay backtest.")
    ap.add_argument("--start", default="1990-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--years", type=int, default=26)
    ap.add_argument("--step-months", type=int, default=3)
    args = ap.parse_args(argv)

    data = prepare_extended_data(start=args.start, end=args.end)
    agg = run_rolling(data, years=args.years, step_months=args.step_months)
    n = len(agg["trend"]["cagr"])
    print(f"{n} rolling {args.years}-yr windows (every {args.step_months} mo), "
          f"starts {agg['_starts'][0].date()}..{agg['_starts'][-1].date()}\n")
    print(format_table(agg))


if __name__ == "__main__":  # pragma: no cover
    main()
