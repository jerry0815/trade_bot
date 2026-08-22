"""Single-path screen for vol-targeted leverage (up-scaling).

Runs 1990-2026 on the single-signal ^NDX sleeve, pre-tax, frictionless,
comparing three L_max caps (3x/4x/5x) of a target-vol leverage rule against
binary-3x and fixed-2x. GO/NO-GO screen, NOT a headline: vol-targeting
rebalances daily, so a frictionless result is a SOFT UPPER BOUND. A real
result requires the friction-aware confirm stage (not in this script).

Run:
    python backtest/vol_target_screen.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester, SMATrendFollowing, VolTargetLeverage
from backtest.dynamic_leverage_screen import calmar, sharpe_from_equity

OUTPUT_PATH = REPO_ROOT / "backtest" / "vol_target_screen_output.md"
START = "1990-01-01"
YEARS = 36
L_MAX_SWEEP = [3.0, 4.0, 5.0]
TARGET_VOL = 0.45


def _kpis(res):
    eq = res["equity_curve"]
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    max_dd = res["max_drawdown"] / 100.0
    return {
        "cagr": cagr, "max_dd": max_dd,
        "calmar": calmar(cagr, max_dd), "sharpe": sharpe_from_equity(eq),
        "avg_lev": res.get("avg_leverage", float("nan")),
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
    rows = [
        ("Binary 3x (baseline)", _run(SMATrendFollowing(atr_multiplier=2.5), 3)),
        ("Fixed 2x (same signal)", _run(SMATrendFollowing(atr_multiplier=2.5), 2)),
    ]
    for lmax in L_MAX_SWEEP:
        rows.append((f"VolTarget (cap {lmax:.0f}x)",
                     _run(VolTargetLeverage(target_vol=TARGET_VOL, l_min=1.0,
                                            l_max=lmax), 3)))
    return rows


def format_table(rows):
    head = ("| Strategy | CAGR | Worst DD | Calmar | Sharpe | Avg Lev | Trades | Rebal |\n"
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    body = ""
    for name, k in rows:
        if k is None:
            body += f"| {name} | — | — | — | — | — | — | — |\n"
            continue
        avg = "—" if k["avg_lev"] != k["avg_lev"] else f"{k['avg_lev']:.2f}x"
        body += (f"| {name} | {k['cagr']*100:.2f}% | {k['max_dd']*100:.2f}% | "
                 f"{k['calmar']:.2f} | {k['sharpe']:.2f} | {avg} | {k['trades']} | "
                 f"{k['rebalances']} |\n")
    return head + body


def main():
    rows = run_suite()
    table = format_table(rows)
    note = ("\n> **Screen only, SOFT UPPER BOUND** — single continuous 1990–2026 path, "
            "single-signal ^NDX sleeve, pre-tax, frictionless. Vol-targeting rebalances "
            "daily; a frictionless result flatters it. A go/no-go, not a headline. A real "
            f"result requires the friction-aware confirm stage. target_vol={TARGET_VOL:.0%}, "
            "fixed/untuned.\n")
    doc = f"# Vol-Targeted Leverage — Screen (1990–2026)\n\n{table}{note}"
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(doc)


if __name__ == "__main__":
    main()
