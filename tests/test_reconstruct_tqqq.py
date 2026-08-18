import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.reconstruct_tqqq import synthetic_returns, calibrate_alpha


def test_synthetic_returns_applies_leverage_and_drag():
    idx = pd.date_range("2005-01-03", periods=3, freq="B")
    r_ndx = pd.Series([0.01, -0.02, 0.0], index=idx)
    rate = pd.Series([0.05, 0.05, 0.05], index=idx)
    out = synthetic_returns(r_ndx, rate, alpha_daily=0.0)
    drag = (0.0095 + 2 * 0.05) / 252
    assert out.iloc[0] == 3 * 0.01 - drag
    assert out.iloc[1] == 3 * -0.02 - drag
    # Zero rate -> only the expense drag remains.
    out0 = synthetic_returns(r_ndx, pd.Series(0.0, index=idx))
    assert abs(out0.iloc[2] - (-0.0095 / 252)) < 1e-12


def test_calibrate_alpha_recovers_constant_gap():
    idx = pd.date_range("2010-01-04", periods=500, freq="B")
    r_syn = pd.Series(0.001, index=idx)                      # steady synthetic path
    syn_cum = (1 + r_syn).cumprod()
    real = syn_cum * np.exp(0.0004 * np.arange(len(idx)))    # real outpaces by 4bp/day
    alpha = calibrate_alpha(r_syn, real)
    assert abs(alpha - 0.0004) < 1e-5


def test_calibrate_alpha_zero_when_matched():
    idx = pd.date_range("2010-01-04", periods=100, freq="B")
    r_syn = pd.Series(0.002, index=idx)
    real = (1 + r_syn).cumprod()
    assert abs(calibrate_alpha(r_syn, real)) < 1e-9
