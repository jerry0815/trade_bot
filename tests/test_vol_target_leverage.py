"""Unit tests for vol-targeted leverage strategy + avg_leverage metric.

Network-free: synthetic frames drive the stats function and the pure
vol-sizing method directly.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester


def _frame(start, in_market, target_leverage=None):
    idx = pd.date_range(start, periods=len(in_market), freq="D")
    n = len(idx)
    data = {
        "in_market": np.asarray(in_market, dtype=bool),
        "BR": np.zeros(n),
        "Daily_Return_1x": np.zeros(n),
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }
    if target_leverage is not None:
        data["target_leverage"] = np.asarray(target_leverage, dtype=float)
    return pd.DataFrame(data, index=idx)


def test_avg_leverage_is_mean_over_in_market_days():
    # in-market leverages: 3, 3, 1.5 -> mean 2.5 (cash days excluded)
    lev = [0.0, 3.0, 3.0, 1.5, 0.0]
    df = _frame("2000-01-01", [x > 0 for x in lev], target_leverage=lev)
    env = Backtester(verbose=False)
    stats = env._calculate_trade_stats(df)
    assert abs(stats["avg_leverage"] - 2.5) < 1e-9


def test_avg_leverage_is_nan_without_target_leverage():
    df = _frame("2000-01-01", [True, True, False])
    env = Backtester(verbose=False)
    stats = env._calculate_trade_stats(df)
    assert math.isnan(stats["avg_leverage"])
