"""Covered-call income optimizer — sweep the config grid and rank by yield.

For each ticker the optimizer runs :func:`options.cc_income.run_cc_income` across
a grid of ``delta × dte × ivr_gate × earnings_rule`` (60 configs), then picks the
config that **maximizes annualized premium yield subject to keeping the shares**:
``Keep Rate ≥ keep_rate_min`` (default 80%) and ``Total-Return Drag ≤ drag_cap``
(default 3 pp/yr), tie-broken by lowest drag. The raw ranked table is emitted too
so the holder can see the whole income-vs-drag frontier.

CLI::

    python -m options.cc_optimizer --tickers NVDA,PLTR,TQQQ --start 2020-01-01 \\
        --out docs/covered-call-income-2026-09-16.md

Backtest-grade ranking signal, not tradeable P&L — see the standing caveats in
the generated report and in ``docs/strategies/covered-call-income.md``.
"""

from __future__ import annotations

import argparse
import itertools

import pandas as pd

from .cc_income import CCConfig, run_cc_income, load_earnings_dates
from .realized_iv import build_iv_frame, load_price_history, vrp_mult_for

DEFAULT_GRID = {
    "delta": [0.10, 0.15, 0.20, 0.25, 0.30],
    "dte": [30, 45],
    "ivr_gate": [0, 30, 50],
    "earnings_rule": ["ignore", "skip"],
}

KEEP_RATE_MIN = 0.80   # fraction
DRAG_CAP = 0.03        # 3 pp/yr


def sweep(price_df, iv_df, earnings_dates, cfg_base: CCConfig, grid=None) -> list[dict]:
    """Run every grid combination and return a list of {params..., kpis...} rows.

    ``cfg_base`` supplies the fixed fields (ticker, shares, vrp_mult, yields);
    the grid overrides ``delta``, ``dte``, ``ivr_gate`` and ``earnings_rule``.
    """
    grid = grid or DEFAULT_GRID
    rows: list[dict] = []
    for delta, dte, ivr_gate, earnings_rule in itertools.product(
        grid["delta"], grid["dte"], grid["ivr_gate"], grid["earnings_rule"]
    ):
        cfg = CCConfig(
            ticker=cfg_base.ticker,
            shares=cfg_base.shares,
            delta=delta,
            dte=dte,
            ivr_gate=ivr_gate,
            earnings_rule=earnings_rule,
            profit_target=cfg_base.profit_target,
            min_dte_exit=cfg_base.min_dte_exit,
            vrp_mult=cfg_base.vrp_mult,
            call_skew_mult=cfg_base.call_skew_mult,
            risk_free=cfg_base.risk_free,
            cash_yield=cfg_base.cash_yield,
            initial_capital=cfg_base.initial_capital,
        )
        res = run_cc_income(price_df, iv_df, earnings_dates, cfg)
        row = {
            "delta": delta,
            "dte": dte,
            "ivr_gate": ivr_gate,
            "earnings_rule": earnings_rule,
        }
        row.update(res.kpis)
        rows.append(row)
    return rows


def score_config(kpis: dict, keep_rate_min: float = KEEP_RATE_MIN, drag_cap: float = DRAG_CAP):
    """Return a sort key ``(eligible, premium_yield, -drag)`` for one config.

    ``eligible`` is True when Keep Rate ≥ ``keep_rate_min`` (fraction) and
    Total-Return Drag ≤ ``drag_cap`` (fraction/yr). Higher tuples rank better:
    eligible configs first, then max premium yield, then min drag. NaNs are
    treated as worst.
    """
    keep = kpis.get("Keep Rate (%)", float("nan")) / 100.0
    drag = kpis.get("Total-Return Drag (pp/yr)", float("nan")) / 100.0
    py = kpis.get("Annualized Premium Yield (%)", float("nan"))

    eligible = (keep == keep and keep >= keep_rate_min) and (drag == drag and drag <= drag_cap)
    py_key = py if py == py else float("-inf")
    drag_key = drag if drag == drag else float("inf")
    return (1 if eligible else 0, py_key, -drag_key)


def recommend(rows: list[dict], keep_rate_min: float = KEEP_RATE_MIN, drag_cap: float = DRAG_CAP) -> dict:
    """Pick the best row by :func:`score_config` (deterministic tie-break)."""
    return max(
        rows,
        key=lambda row: (
            *score_config(row, keep_rate_min, drag_cap),
            # Fully deterministic tie-break on the config params.
            -row["delta"], -row["dte"], -row["ivr_gate"], row["earnings_rule"],
        ),
    )


# --- reporting ---------------------------------------------------------------- #

_REPORT_COLS = [
    ("delta", "Δ"),
    ("dte", "DTE"),
    ("ivr_gate", "IVR≥"),
    ("earnings_rule", "Earnings"),
    ("Annualized Premium Yield (%)", "Prem Yield %/yr"),
    ("Keep Rate (%)", "Keep %"),
    ("Total-Return Drag (pp/yr)", "Drag pp/yr"),
    ("CAGR (%)", "CAGR %"),
    ("Buy & Hold CAGR (%)", "B&H CAGR %"),
    ("Max Drawdown (MDD %)", "MDD %"),
    ("Total Cycles", "Cycles"),
]


def _fmt(key: str, val) -> str:
    if isinstance(val, str):
        return val
    if val != val:  # NaN
        return "n/a"
    if key == "delta":
        return f"{val:.2f}"
    if key in ("dte", "ivr_gate", "Total Cycles"):
        return f"{int(val):,}"
    return f"{val:,.2f}"


def _table(rows: list[dict], top_n: int | None = None) -> str:
    ranked = sorted(
        rows,
        key=lambda row: (*score_config(row), -row["delta"], -row["dte"], -row["ivr_gate"]),
        reverse=True,
    )
    if top_n is not None:
        ranked = ranked[:top_n]
    headers = [label for _, label in _REPORT_COLS]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in ranked:
        cells = [_fmt(key, row.get(key)) for key, _ in _REPORT_COLS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _recommendation_line(rec: dict) -> str:
    tag = "" if score_config(rec)[0] else " ⚠️ (no config met the keep-rate/drag filter — closest shown)"
    return (
        f"**Recommended:** Δ {rec['delta']:.2f}, {int(rec['dte'])} DTE, "
        f"IVR≥{int(rec['ivr_gate'])}, earnings `{rec['earnings_rule']}` — "
        f"premium yield {_fmt('Annualized Premium Yield (%)', rec.get('Annualized Premium Yield (%)'))}%/yr, "
        f"keep rate {_fmt('Keep Rate (%)', rec.get('Keep Rate (%)'))}%, "
        f"drag {_fmt('Total-Return Drag (pp/yr)', rec.get('Total-Return Drag (pp/yr)'))} pp/yr."
        f"{tag}"
    )


_CAVEATS = (
    "## How to read this\n\n"
    "The objective is **maximum premium income while keeping the shares** — a "
    "different goal from the [options overlay finding]"
    "(strategies/options-overlay.md), which asked about *total return* on a "
    "leveraged trend sleeve and was negative. Here the shares are held "
    "regardless, so the ranked metric is **annualized premium yield**, filtered "
    "to **Keep Rate ≥ 80%** (fraction of cycles whose short call did not finish "
    "ITM) and **Total-Return Drag ≤ 3 pp/yr** (CAGR given up vs buy & hold), "
    "tie-broken by lowest drag. Lower delta / farther OTM keeps more shares.\n\n"
    "### Modeling caveats — backtest-grade ranking signal, not tradeable P&L\n\n"
    "- **Implied vol is a realized-vol proxy** (`implied ≈ realized × vrp_mult`, "
    "per-ticker ~1.10–1.20), not a live chain. It is an approximation, uniform "
    "across names so the methodology is self-contained.\n"
    "- Options are **cash-settled at intrinsic on expiry; the shares are always "
    "retained** (same convention as the overlay engine). An ITM expiry counts as "
    "an 'assigned cycle' — the cycle where the shares *would* have been called "
    "away — and lowers the keep rate.\n"
    "- Premium and buybacks settle into a cash balance that earns `cash_yield`; "
    "the buy & hold baseline holds the identical shares + starting cash.\n"
    "- Skew is a fixed multiplicative call offset, not a fitted surface.\n"
    "- Earnings dates use yfinance when available, else a synthetic ~quarterly "
    "cadence (an approximation) for the `skip` rule.\n"
    "- **Not modeled:** bid/ask, fills, commissions, early assignment, borrow, or "
    "the tax drag of short-term premium.\n\n"
)


def build_report(per_ticker: dict[str, dict], span: str) -> str:
    parts = [
        f"# Covered-Call Income Optimizer ({span})\n",
        "Per-ticker grid sweep (Δ × DTE × IVR-gate × earnings-rule = 60 configs), "
        "ranked by annualized premium yield subject to keeping the shares.\n",
        _CAVEATS,
    ]
    for ticker, payload in per_ticker.items():
        parts.append(f"## {ticker}\n")
        parts.append(payload["recommendation"] + "\n")
        parts.append("Top configs by premium yield (eligible first):\n")
        parts.append(payload["table"] + "\n")
    parts.append(
        "---\n\nSee [`strategies/covered-call-income.md`](strategies/covered-call-income.md) "
        "for the strategy write-up and the contrast with the negative overlay finding.\n"
    )
    return "\n".join(parts)


def run_ticker(ticker: str, start: str, end: str | None, capital: float) -> dict:
    """Load data, sweep the grid, and return {rows, recommendation, table} for one ticker."""
    px = load_price_history(ticker, start=start, end=end)
    iv_frame = build_iv_frame(px["Close"], vrp_mult=vrp_mult_for(ticker))
    common = px.index.intersection(iv_frame.index)
    px = px.loc[common]
    iv_frame = iv_frame.loc[common]
    earnings = load_earnings_dates(ticker, start=start, end=end)

    cfg_base = CCConfig(ticker=ticker, initial_capital=capital)
    rows = sweep(px, iv_frame, earnings, cfg_base)
    rec = recommend(rows)
    return {
        "rows": rows,
        "recommendation": _recommendation_line(rec),
        "table": _table(rows, top_n=12),
        "best": rec,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Covered-call income optimizer (per-ticker grid sweep).")
    ap.add_argument("--tickers", default="NVDA,PLTR,TQQQ")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--out", default=None, help="Write a Markdown report to this path.")
    args = ap.parse_args(argv)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    per_ticker: dict[str, dict] = {}
    spans = []
    for ticker in tickers:
        print(f"Sweeping {ticker} ...")
        payload = run_ticker(ticker, args.start, args.end, args.capital)
        per_ticker[ticker] = payload
        print("  " + payload["recommendation"])

    span = f"{args.start} to {args.end or 'today'}"
    report = build_report(per_ticker, span)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"Wrote {args.out}")
    else:
        print("\n" + report)


if __name__ == "__main__":  # pragma: no cover
    main()
