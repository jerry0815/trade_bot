import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.iv_loader import compute_iv_rank


def _series(vals):
    idx = pd.date_range("2020-01-01", periods=len(vals), freq="B")
    return pd.Series(vals, index=idx, dtype=float)


def test_iv_rank_endpoints():
    # A clean ramp: the min sits at 0, the max at 100 within the window.
    vals = list(range(20, 120))  # 100 points, monotonically rising
    df = compute_iv_rank(_series(vals), lookback=100)
    # Last row: current == rolling max => rank 100.
    assert abs(df["IV_Rank"].iloc[-1] - 100.0) < 1e-6


def test_iv_rank_midpoint():
    # Constant then a single value halfway between min and max.
    vals = [10.0] * 60 + [30.0] * 60 + [20.0]
    df = compute_iv_rank(_series(vals), lookback=120)
    # Final point 20 sits halfway between window min 10 and max 30 => ~50.
    assert abs(df["IV_Rank"].iloc[-1] - 50.0) < 1e-6


def test_flat_window_maps_to_mid_rank():
    vals = [15.0] * 130
    df = compute_iv_rank(_series(vals), lookback=120)
    assert (df["IV_Rank"] == 50.0).all()


def test_iv_rank_bounded_0_100():
    rng = np.random.default_rng(0)
    vals = 20 + 10 * rng.standard_normal(400).cumsum() / 20
    vals = np.abs(vals) + 5
    df = compute_iv_rank(_series(vals), lookback=252)
    assert df["IV_Rank"].min() >= -1e-9
    assert df["IV_Rank"].max() <= 100 + 1e-9
