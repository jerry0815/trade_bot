"""Benchmark suite: run the 4 comparison models and print/save the KPI table.

Models
------
1. buy_hold  : 100% Buy & Hold TQQQ.
2. trend     : 3-state SMA+ATR regime allocation (100% TQQQ / 50-50 / 100% SGOV),
               no options. A refinement of the production binary bot (adds the
               transition sleeve), so its standalone return differs from the
               README's binary numbers.
3. static_cc : Model 2 + mechanical 30-DTE ~20Δ covered calls in the bull regime,
               ignoring IV-Rank.
4. dynamic   : Model 2 + the full two-sided IV matrix (put-debit hedges at low IV,
               covered calls / CSPs / bull-put spreads at high IV).

Usage
-----
    python -m options.run_benchmark                      # 2018-01-01 .. today
    python -m options.run_benchmark --start 2018-01-01 --end 2026-08-17
    python -m options.run_benchmark --out docs/options-overlay-benchmark.md

Requires network access for yfinance (TQQQ + ^VXN). The indicator math is
self-contained here so the options package does not depend on the trend engine's
internals.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .iv_loader import compute_iv_rank
from .overlay_backtest import run_model, BacktestResult

MODELS = ["buy_hold", "trend", "static_cc", "dynamic"]
MODEL_LABELS = {
    "buy_hold": "Model 1 — Buy & Hold TQQQ",
    "trend": "Model 2 — Trend (SMA+ATR, no options)",
    "static_cc": "Model 3 — Static Covered Calls",
    "dynamic": "Model 4 — Dynamic Two-Sided Engine",
}


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def prepare_overlay_data(
    start: str = "2018-01-01",
    end: str | None = None,
    tqqq_ticker: str = "TQQQ",
    iv_ticker: str = "^VXN",
    sma_period: int = 200,
) -> pd.DataFrame:
    """Download TQQQ + ^VXN and assemble the daily frame the simulator needs."""
    from ._net import download

    # Warm up indicators by starting ~1.5y before the requested window.
    warmup_start = (pd.to_datetime(start) - pd.DateOffset(months=18)).strftime("%Y-%m-%d")

    tqqq = download(tqqq_ticker, start=warmup_start, end=end)
    vxn = download(iv_ticker, start=warmup_start, end=end)
    if tqqq is None or tqqq.empty:
        raise RuntimeError(f"No data for {tqqq_ticker!r}")
    if vxn is None or vxn.empty:
        raise RuntimeError(f"No data for {iv_ticker!r}")
    for frame in (tqqq, vxn):
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)

    df = pd.DataFrame(index=tqqq.index)
    df["Close"] = tqqq["Close"]
    df["High"] = tqqq["High"]
    df["Low"] = tqqq["Low"]
    df["SMA"] = df["Close"].rolling(sma_period, min_periods=sma_period).mean()
    df["ATR"] = _atr(tqqq)
    df["RSI"] = _rsi(df["Close"])

    iv = compute_iv_rank(vxn["Close"])
    df["IV"] = iv["IV"].reindex(df.index).ffill()
    df["IV_Rank"] = iv["IV_Rank"].reindex(df.index).ffill()

    df = df.dropna(subset=["Close", "SMA", "ATR"])
    df = df[df.index >= pd.to_datetime(start)]
    if end is not None:
        df = df[df.index <= pd.to_datetime(end)]
    return df


def run_suite(data: pd.DataFrame, **cfg_kwargs) -> dict[str, BacktestResult]:
    return {m: run_model(data, m, **cfg_kwargs) for m in MODELS}


def _fmt(key: str, val) -> str:
    if val != val:  # NaN
        return "n/a"
    # Ratios first: their labels can contain a stray "%" (e.g. "Rf=4.5%").
    if "Ratio" in key:
        return f"{val:,.2f}"
    if "($)" in key:
        return f"${val:,.0f}"
    if "Days" in key or "Trades" in key:
        return f"{int(val):,}"
    if "(%" in key or "%)" in key:
        return f"{val:,.2f}%"
    return f"{val:,.2f}"


def format_table(results: dict[str, BacktestResult]) -> str:
    kpi_order = list(next(iter(results.values())).kpis.keys())
    headers = ["Metric"] + [MODEL_LABELS[m] for m in MODELS]
    rows = [headers, ["---"] * len(headers)]
    for kpi in kpi_order:
        row = [kpi] + [_fmt(kpi, results[m].kpis[kpi]) for m in MODELS]
        rows.append(row)
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the 4-model options-overlay benchmark.")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--out", default=None, help="Write a Markdown report to this path.")
    args = ap.parse_args(argv)

    print(f"Preparing data {args.start} .. {args.end or 'today'} ...")
    data = prepare_overlay_data(start=args.start, end=args.end)
    print(f"  {len(data)} trading days, "
          f"{data.index[0].date()} .. {data.index[-1].date()}")

    results = run_suite(data, initial_capital=args.capital)
    table = format_table(results)
    print("\n" + table + "\n")

    if args.out:
        span = f"{data.index[0].date()} to {data.index[-1].date()}"
        report = (
            f"# Options Overlay Benchmark ({span})\n\n"
            f"Initial capital: ${args.capital:,.0f}. TQQQ actual prices; ^VXN as IV proxy.\n\n"
            f"{table}\n\n"
            f"See `options/README.md` for model definitions and accounting assumptions.\n"
        )
        with open(args.out, "w") as fh:
            fh.write(report)
        print(f"Wrote {args.out}")


if __name__ == "__main__":  # pragma: no cover
    main()
