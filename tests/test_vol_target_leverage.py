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
from backtest.strat_backtest import VolTargetLeverage


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


def _vol_frame(daily_moves):
    """Build a Close series from a list of daily returns (Close[0]=100)."""
    closes = [100.0]
    for r in daily_moves:
        closes.append(closes[-1] * (1 + r))
    idx = pd.date_range("2000-01-01", periods=len(closes), freq="D")
    return pd.Series(closes, index=idx)


def test_size_leverage_hits_l_max_in_calm_regime():
    # Very low, steady vol while in-market -> target_vol/realized_vol is large
    # -> clamped to l_max.
    close = _vol_frame([0.0005] * 40)          # ~tiny daily moves
    in_market = pd.Series(True, index=close.index)
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=4.0, vol_window=20)
    # After warm-up (>=vol_window+1 days), leverage should sit at the cap.
    assert lev[-1] == 4.0


def test_size_leverage_hits_l_min_in_high_vol_regime():
    # Large alternating daily moves -> high realized vol -> ratio < 1 ->
    # clamped up to l_min.
    close = _vol_frame([0.06, -0.06] * 20)
    in_market = pd.Series(True, index=close.index)
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=4.0, vol_window=20)
    assert lev[-1] == 1.0


def test_size_leverage_is_zero_out_of_market():
    close = _vol_frame([0.0005] * 40)
    in_market = pd.Series(False, index=close.index)   # never in market
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=4.0, vol_window=20)
    assert np.all(lev == 0.0)


def test_size_leverage_is_lookahead_free():
    # A single huge move at index t must not change leverage until t+1
    # (realized vol is shifted one day).
    moves = [0.001] * 30
    moves[25] = 0.15                       # vol spike on day 26 (index 26 in close)
    close = _vol_frame(moves)
    in_market = pd.Series(True, index=close.index)
    lev = VolTargetLeverage._size_leverage(close, in_market,
                                           target_vol=0.45, l_min=1.0,
                                           l_max=5.0, vol_window=20)
    # The spike is the return into close index 26; shifted vol means leverage
    # at index 26 is still the pre-spike (high) level, and index 27 drops.
    assert lev[26] > lev[27]


def test_strategy_wires_both_columns_on_uptrend():
    # 260-day steady uptrend so SMA200 is valid and price sits above the band.
    n = 260
    idx = pd.date_range("2000-01-01", periods=n, freq="D")
    close = pd.Series(100.0 * (1.001 ** np.arange(n)), index=idx)
    df = pd.DataFrame({
        "Close": close.values,
        "ATR": np.full(n, 0.5),
        "Daily_Return_1x": close.pct_change().fillna(0).values,
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }, index=idx)
    strat = VolTargetLeverage(l_max=4.0)
    out, _ = strat.generate_signals(df.copy())
    assert "target_leverage" in out.columns
    assert (out["in_market"] == (out["target_leverage"] > 0)).all()
    # Warm-up (first vol_window days) is cash; later in-market days are levered.
    assert out["target_leverage"].iloc[:5].eq(0.0).all()
    assert out["target_leverage"].iloc[-1] > 0
