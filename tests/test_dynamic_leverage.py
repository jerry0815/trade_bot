"""Unit tests for per-day variable leverage in the portfolio math engine.

Network-free: builds synthetic price frames and drives
Backtester._run_portfolio_math directly.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester


def _frame(start, in_market, ret=0.0, o2c=0.0, ovn=0.0, br=0.0, target_leverage=None):
    """Synthetic daily frame. Scalar return args are broadcast to every row."""
    idx = pd.date_range(start, periods=len(in_market), freq="D")
    n = len(idx)
    data = {
        "in_market": np.asarray(in_market, dtype=bool),
        "BR": np.full(n, br, dtype=float),
        "Daily_Return_1x": np.full(n, ret, dtype=float),
        "Open2Close": np.full(n, o2c, dtype=float),
        "Overnight_Return": np.full(n, ovn, dtype=float),
    }
    if target_leverage is not None:
        data["target_leverage"] = np.asarray(target_leverage, dtype=float)
    return pd.DataFrame(data, index=idx)


def test_no_target_leverage_column_matches_scalar():
    # A frame WITHOUT target_leverage must reproduce the scalar-leverage path.
    mask = [True] * 10
    df = _frame("2000-01-01", mask, ret=0.01, o2c=0.008, ovn=0.002, br=0.05)
    env = Backtester(leverage=3, expense_ratio=0.0095, verbose=False)
    baseline = env._run_portfolio_math(df.copy())["final_value"]

    # Same frame WITH an explicit constant 3x vector must match exactly.
    df2 = df.copy()
    df2["target_leverage"] = 3.0
    got = env._run_portfolio_math(df2)["final_value"]
    assert got == baseline


def test_constant_2x_vector_matches_scalar_2x():
    mask = [True] * 10
    df = _frame("2000-01-01", mask, ret=0.01, o2c=0.008, ovn=0.002, br=0.05)
    env3 = Backtester(leverage=2, expense_ratio=0.0095, verbose=False)
    scalar_2x = env3._run_portfolio_math(df.copy())["final_value"]

    df2 = df.copy()
    df2["target_leverage"] = 2.0
    env_any = Backtester(leverage=3, expense_ratio=0.0095, verbose=False)  # scalar ignored
    got = env_any._run_portfolio_math(df2)["final_value"]
    assert abs(got - scalar_2x) < 1e-9
