"""Unit tests for the 'Worst DD vs Initial' metric in summarize_rolling_results.

Network-free: builds a synthetic RollingBacktester-style result frame and a
stub strategy (only .name is read), so no market data is needed.
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import summarize_rolling_results


class _Stub:
    def __init__(self, name):
        self.name = name


def _frame(name, twrs, dds, ddvis, trades):
    return pd.DataFrame({
        "Start Date": pd.date_range("2000-01-01", periods=len(twrs), freq="MS"),
        f"{name} TWR (%)": twrs,
        f"{name} Max DD (%)": dds,
        f"{name} Max DD vs Initial (%)": ddvis,
        f"{name} Total Trades": trades,
    })


def test_worst_dd_vs_initial_is_min_of_column():
    df = _frame("S", twrs=[20, 15, 25], dds=[-60, -50, -64],
                ddvis=[-40, -10, -55], trades=[10, 12, 11])
    out = summarize_rolling_results(df, [_Stub("S")])[0]
    assert out["Worst DD vs Initial"] == -55        # deepest below-initial dip
    assert out["Worst DD"] == -64                    # unchanged peak-to-trough


def test_worst_dd_vs_initial_zero_when_never_below_initial():
    # A window set that never dipped below the starting fund -> all zeros.
    df = _frame("S", twrs=[20, 15, 25], dds=[-60, -50, -64],
                ddvis=[0.0, 0.0, 0.0], trades=[10, 12, 11])
    out = summarize_rolling_results(df, [_Stub("S")])[0]
    assert out["Worst DD vs Initial"] == 0.0


def test_absent_column_yields_nan_not_crash():
    # Older frames without the new column must not raise.
    df = pd.DataFrame({
        "Start Date": pd.date_range("2000-01-01", periods=2, freq="MS"),
        "S TWR (%)": [20, 15],
        "S Max DD (%)": [-60, -50],
        "S Total Trades": [10, 12],
    })
    out = summarize_rolling_results(df, [_Stub("S")])[0]
    assert out["Worst DD vs Initial"] != out["Worst DD vs Initial"]  # NaN
    assert out["Worst DD"] == -60
