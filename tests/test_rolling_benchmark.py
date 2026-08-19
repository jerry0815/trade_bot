import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.rolling_benchmark import window_starts, format_table


def test_window_starts_fit_within_data():
    idx = pd.date_range("1990-01-01", "2026-08-14", freq="B")
    starts = window_starts(idx, years=26, step_months=3)
    assert len(starts) > 30
    # Every 26-year window must end on or before the last date.
    assert all(s + pd.DateOffset(years=26) <= idx[-1] for s in starts)
    # The next step past the last start would overrun.
    assert starts[-1] + pd.DateOffset(months=3) + pd.DateOffset(years=26) > idx[-1]


def test_format_table_reports_avg_worst():
    agg = {"trend": {"cagr": [20.0, 22.0, 24.0], "dd": [-40.0, -65.0, -50.0],
                     "ddinit": [-30.0, -51.0, -40.0], "trades": [0, 0, 0]}}
    out = format_table(agg, models=["trend"])
    assert "Avg CAGR" in out
    assert "22.0%" in out          # avg of 20/22/24
    assert "-65.0%" in out         # worst DD (min)
