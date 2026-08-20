"""Unit tests for monthly-DCA cash injection in the portfolio math engine.

Network-free: builds a synthetic zero-return price frame and drives
Backtester._run_portfolio_math directly, so no market data is needed. With
all daily returns pinned to zero, portfolio value only moves via injections,
making the arithmetic exactly predictable.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import Backtester


def _flat_frame(start, periods):
    """Daily calendar with every return column zero and always in-market.

    BR=0 -> no leverage drag, no cash yield; every daily return is 0, so the
    only thing that changes portfolio_value is a DCA injection.
    """
    idx = pd.date_range(start, periods=periods, freq="D")
    n = len(idx)
    return pd.DataFrame({
        "in_market": np.ones(n, dtype=bool),
        "BR": np.zeros(n),
        "Daily_Return_1x": np.zeros(n),
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }, index=idx)


def test_monthly_dca_injects_once_per_new_month():
    # Jan 1 -> Apr 10 spans four calendar months. The start month (Jan) gets
    # only the initial fund; a new month rolls over on Feb 1, Mar 1, Apr 1 ->
    # three injections of $2,000.
    df = _flat_frame("2000-01-01", periods=101)  # through 2000-04-10
    env = Backtester(initial_fund=10000, monthly_dca=2000, leverage=1,
                     expense_ratio=0.0, verbose=False)
    res = env._run_portfolio_math(df)

    assert res["total_invested"] == 10000 + 3 * 2000   # 16,000 principal
    assert res["final_value"] == 16000                 # zero returns, all cash preserved


def _frame_with_mask(start, in_market_mask):
    """Flat (zero-return) daily calendar with a caller-supplied in_market path."""
    idx = pd.date_range(start, periods=len(in_market_mask), freq="D")
    n = len(idx)
    return pd.DataFrame({
        "in_market": np.asarray(in_market_mask, dtype=bool),
        "BR": np.zeros(n),
        "Daily_Return_1x": np.zeros(n),
        "Open2Close": np.zeros(n),
        "Overnight_Return": np.zeros(n),
    }, index=idx)


def test_dca_injected_during_hold_is_not_taxed_as_gain():
    # Enter on day 0, hold across a Feb 1 injection, exit mid-Feb. Zero market
    # returns throughout, so there is NO real capital gain — only the $2,000
    # contributed mid-hold. That injected principal must NOT be taxed as a gain.
    # 2000-01-01 + 70 days spans Jan/Feb/Mar (2000 is a leap year): injections
    # fire on Feb 1 (idx 31, during the hold) and Mar 1 (idx 60, after exit).
    n = 70
    mask = [True] * 45 + [False] * (n - 45)  # exit on day 45 (mid-Feb)
    df = _frame_with_mask("2000-01-01", mask)
    env = Backtester(initial_fund=10000, monthly_dca=2000, leverage=1,
                     expense_ratio=0.0, apply_tax=True, verbose=False)
    res = env._run_portfolio_math(df)

    assert res["total_invested"] == 14000            # two injections total
    assert res["total_tax_paid"] == 0.0              # no real gain -> no tax
    assert res["final_value"] == 14000               # principal fully preserved


def test_monthly_dca_zero_is_lump_sum():
    # monthly_dca defaults to 0 -> no injections, principal is the initial fund.
    df = _flat_frame("2000-01-01", periods=101)
    env = Backtester(initial_fund=10000, leverage=1, expense_ratio=0.0,
                     verbose=False)
    res = env._run_portfolio_math(df)

    assert res["total_invested"] == 10000
    assert res["final_value"] == 10000
