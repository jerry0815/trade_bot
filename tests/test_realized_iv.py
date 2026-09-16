import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.realized_iv import (
    realized_vol,
    implied_proxy,
    build_iv_frame,
    vrp_mult_for,
    DEFAULT_VRP_MULT,
)


def _series(returns, start=100.0):
    prices = start * np.exp(np.cumsum(np.r_[0.0, returns]))
    idx = pd.bdate_range("2021-01-01", periods=len(prices))
    return pd.Series(prices, index=idx)


def test_realized_vol_zero_on_constant_return_series():
    # Pure exponential growth => every daily log-return identical => vol ~ 0.
    close = _series([np.log(1.001)] * 300)
    rv = realized_vol(close, window=21)
    assert (rv.abs() < 1e-9).all()


def test_realized_vol_matches_known_constant_vol():
    # iid normal returns with a known sigma; annualized rv should be close.
    rng = np.random.default_rng(7)
    daily_sigma = 0.02
    close = _series(rng.normal(0.0, daily_sigma, 2000))
    rv = realized_vol(close, window=63)
    expected = daily_sigma * np.sqrt(252)
    assert abs(rv.mean() - expected) < 0.05 * expected


def test_implied_proxy_scales_linearly():
    rng = np.random.default_rng(1)
    close = _series(rng.normal(0.0, 0.015, 500))
    rv = realized_vol(close)
    iv = implied_proxy(rv, 1.15)
    assert np.allclose(iv.values, rv.values * 1.15)
    # Doubling the multiplier doubles the proxy.
    assert np.allclose(implied_proxy(rv, 2.0).values, 2.0 * implied_proxy(rv, 1.0).values)


def test_build_iv_frame_shape_and_bounds():
    rng = np.random.default_rng(2)
    close = _series(rng.normal(0.0003, 0.02, 800))
    frame = build_iv_frame(close, vrp_mult=1.2)
    assert list(frame.columns) == ["RealizedVol", "IV", "IV_Rank"]
    assert (frame["IV_Rank"] >= -1e-9).all() and (frame["IV_Rank"] <= 100 + 1e-9).all()
    # IV is realized * vrp_mult on the aligned rows.
    assert np.allclose(frame["IV"].values, frame["RealizedVol"].values * 1.2)


def test_vrp_mult_per_ticker():
    assert vrp_mult_for("PLTR") == 1.20
    assert vrp_mult_for("TQQQ") == 1.10
    assert vrp_mult_for("UNKNOWN") == DEFAULT_VRP_MULT
