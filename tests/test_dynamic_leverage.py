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
from backtest.strat_backtest import DynamicLeverageTrend


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


def _final_from_daily(returns):
    """Compound a list of daily returns into a growth factor."""
    f = 1.0
    for r in returns:
        f *= (1 + r)
    return f


def test_gear_change_day_uses_overnight_old_intraday_new():
    # Day 0: enter at 3x. Day 1: hold 3x. Day 2: gear-change 3x -> 1.5x.
    # BR=0 so drag=0 and cash_ret=0; isolates the return formula.
    lev = [3.0, 3.0, 1.5]
    df = _frame("2000-01-01", [True, True, True],
                ret=0.010, o2c=0.006, ovn=0.004, br=0.0, target_leverage=lev)
    env = Backtester(leverage=3, expense_ratio=0.0, verbose=False)
    res = env._run_portfolio_math(df)

    # Day0 entry: o2c*3 ; Day1 hold: ret*3 ; Day2 gear-change: ovn*3 + o2c*1.5
    expected = _final_from_daily([
        0.006 * 3.0,
        0.010 * 3.0,
        0.004 * 3.0 + 0.006 * 1.5,
    ])
    assert abs(res["final_value"] / 10000 - expected) < 1e-9


def test_exit_day_uses_overnight_at_old_leverage():
    # Day 0: enter 2x. Day 1: hold 2x. Day 2: exit to cash.
    lev = [2.0, 2.0, 0.0]
    df = _frame("2000-01-01", [True, True, False],
                ret=0.010, o2c=0.006, ovn=0.004, br=0.0, target_leverage=lev)
    env = Backtester(leverage=2, expense_ratio=0.0, verbose=False)
    res = env._run_portfolio_math(df)

    expected = _final_from_daily([
        0.006 * 2.0,   # entry: open->close at 2x
        0.010 * 2.0,   # hold
        0.004 * 2.0,   # exit: overnight gap at the OLD (2x) exposure
    ])
    assert abs(res["final_value"] / 10000 - expected) < 1e-9


def test_cash_day_earns_money_market_only():
    # Never in market: every day earns BR*0.8/252, at no leverage.
    lev = [0.0, 0.0, 0.0]
    df = _frame("2000-01-01", [False, False, False],
                ret=0.05, o2c=0.05, ovn=0.05, br=0.05, target_leverage=lev)
    env = Backtester(leverage=3, expense_ratio=0.0095, verbose=False)
    res = env._run_portfolio_math(df)

    daily_cash = 0.05 * 0.8 / 252
    expected = _final_from_daily([daily_cash] * 3)
    assert abs(res["final_value"] / 10000 - expected) < 1e-9


def _band_frame(closes, sma=100.0, atr=10.0, mult=2.5):
    """Frame where Close crosses a fixed SMA+/-mult*ATR band.

    Upper = sma + mult*atr, Lower = sma - mult*atr. Above upper -> bull (3x),
    below lower -> bear (cash), between -> transition (middle gear).
    """
    idx = pd.date_range("2000-01-01", periods=len(closes), freq="D")
    n = len(idx)
    return pd.DataFrame({
        "Close": np.asarray(closes, dtype=float),
        "SMA": np.full(n, sma),
        "ATR": np.full(n, atr),
        "Daily_Return_1x": np.zeros(n),
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }, index=idx)


def test_three_states_map_to_three_gears():
    # Upper=125, Lower=75. Closes chosen to sit clearly bull / mid / bear, one
    # distinct state per day so the shift is load-bearing: if _add_indicator_logic
    # forgot the .shift(1), tl would be [3.0, 1.5, 0.0] instead of the asserted
    # [3.0, 3.0, 1.5].
    strat = DynamicLeverageTrend(middle_gear=1.5)
    closes = [130, 100, 60]   # bull, mid, bear
    df = _band_frame(closes)
    out, _ = strat.generate_signals(df.copy())

    # Pre-shift state is [3.0, 1.5, 0.0]; day 0 seeds initial=3.0 (its own
    # state), then each day's target_leverage reflects YESTERDAY's state.
    tl = out["target_leverage"].tolist()
    assert tl[0] == 3.0     # day0 seed = day0's own (bull) state
    assert tl[1] == 3.0     # yesterday (day0) bull -> 3x today
    assert tl[2] == 1.5     # yesterday (day1) mid  -> middle gear today
    assert (out["in_market"] == (out["target_leverage"] > 0)).all()


def test_target_leverage_is_lookahead_free():
    # A single bull day surrounded by mid days must not raise today's leverage
    # until the day AFTER the bull close (signal shifted by 1).
    strat = DynamicLeverageTrend(middle_gear=1.0)
    closes = [100, 130, 100]   # mid, bull, mid
    df = _band_frame(closes)
    out, _ = strat.generate_signals(df.copy())
    tl = out["target_leverage"].tolist()
    # The bull close is day 1; its 3x exposure may only appear on day 2.
    assert tl[1] != 3.0
    assert tl[2] == 3.0
