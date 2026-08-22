"""Single-path screen (spec §6) for the dynamic-leverage 3-gear idea.

Runs 1990-2026 on the single-signal ^NDX sleeve, pre-tax, comparing three
middle gears against the binary-3x baseline and fixed-2x TQQQ. This is a
GO/NO-GO screen, not a headline: single path, frictionless. A real result
requires the rolling + reconstruction confirm stage (not in this script).

Run:
    python backtest/dynamic_leverage_screen.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    Backtester, SMATrendFollowing, DynamicLeverageTrend,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "dynamic_leverage_screen_output.md"
START = "1990-01-01"
YEARS = 36
MIDDLE_GEARS = [1.0, 1.5, 2.0]


def calmar(cagr, max_dd):
    """CAGR / |MaxDD|. max_dd is a fraction <= 0; 0 drawdown -> inf."""
    if max_dd == 0:
        return float("inf")
    return cagr / abs(max_dd)


def sharpe_from_equity(equity, rf=0.0):
    """Annualised Sharpe from a daily equity curve (252-day convention)."""
    daily = equity.pct_change().dropna()
    if daily.std() == 0:
        return float("inf")
    return float((daily.mean() - rf / 252) / daily.std() * np.sqrt(252))


def _kpis(res):
    eq = res["equity_curve"]
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    max_dd = res["max_drawdown"] / 100.0
    return {
        "cagr": cagr,
        "max_dd": max_dd,
        "calmar": calmar(cagr, max_dd),
        "sharpe": sharpe_from_equity(eq),
        "trades": res.get("total_trades", 0),
        "rebalances": res.get("rebalances", 0),
    }


def _run(strategy, leverage):
    env = Backtester(base_ticker="^NDX", signal_ticker="^NDX",
                     start_date=START, period_years=YEARS, leverage=leverage,
                     expense_ratio=0.0095, initial_fund=10000, verbose=False)
    res = env.run(strategy)
    return _kpis(res) if res else None


def run_suite():
    rows = []
    # Baseline 1: binary 3x-or-cash (single-signal trend).
    rows.append(("Binary 3x (baseline)",
                 _run(SMATrendFollowing(atr_multiplier=2.5), leverage=3)))
    # Baseline 2: fixed 2x, same signal.
    rows.append(("Fixed 2x (same signal)",
                 _run(SMATrendFollowing(atr_multiplier=2.5), leverage=2)))
    # Candidates: 3-gear with each middle gear. Engine leverage is ignored
    # because the strategy emits target_leverage; pass 3 for clarity.
    for mg in MIDDLE_GEARS:
        rows.append((f"3-Gear (mid {mg}x)",
                     _run(DynamicLeverageTrend(middle_gear=mg), leverage=3)))
    return rows


def format_table(rows):
    head = ("| Strategy | CAGR | Worst DD | Calmar | Sharpe | Trades | Rebal |\n"
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    body = ""
    for name, k in rows:
        if k is None:
            body += f"| {name} | — | — | — | — | — | — |\n"
            continue
        body += (f"| {name} | {k['cagr']*100:.2f}% | {k['max_dd']*100:.2f}% | "
                 f"{k['calmar']:.2f} | {k['sharpe']:.2f} | {k['trades']} | "
                 f"{k['rebalances']} |\n")
    return head + body


def main():
    rows = run_suite()
    table = format_table(rows)
    note = ("\n> **Screen only** — single continuous 1990–2026 path, single-signal "
            "^NDX sleeve, pre-tax, frictionless. A go/no-go, not a headline. "
            "A real result requires the rolling + reconstruction confirm stage.\n")
    doc = f"# Dynamic-Leverage 3-Gear — Screen (1990–2026)\n\n{table}{note}"
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(doc)


if __name__ == "__main__":
    main()
