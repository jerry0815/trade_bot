"""Tests for the persistent on-disk data cache in strat_backtest.

Network-free: yfinance is monkeypatched. Verifies that get_cached_data reads a
saved file instead of downloading, and that a first download is written to the
data folder for reuse.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import backtest.strat_backtest as sb


def _ohlc(dates):
    n = len(dates)
    return pd.DataFrame(
        {"Open": range(1, n + 1), "High": range(2, n + 2), "Low": range(0, n),
         "Close": range(1, n + 1), "Adj Close": range(1, n + 1), "Volume": [100] * n},
        index=pd.DatetimeIndex(dates, name="Date"),
    ).astype(float)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "DATA_DIR", tmp_path)
    sb.DATA_CACHE.clear()
    sb.SIGNAL_CACHE.clear()
    yield
    sb.DATA_CACHE.clear()
    sb.SIGNAL_CACHE.clear()


def test_reads_from_disk_without_downloading(tmp_path, monkeypatch):
    saved = _ohlc(pd.date_range("2000-01-03", periods=5, freq="D"))
    saved.to_csv(tmp_path / "FAKE.csv")

    def _boom(*a, **k):
        raise AssertionError("must not download when a data file exists")
    monkeypatch.setattr(sb.yf, "download", _boom)

    out = sb.get_cached_data("FAKE")
    assert list(out.columns) == list(saved.columns)
    assert out["Close"].tolist() == saved["Close"].tolist()
    assert isinstance(out.index, pd.DatetimeIndex)


def test_first_download_is_saved_to_data_folder(tmp_path, monkeypatch):
    fetched = _ohlc(pd.date_range("2010-06-01", periods=4, freq="D"))
    monkeypatch.setattr(sb.yf, "download", lambda *a, **k: fetched.copy())

    out = sb.get_cached_data("^ABC")           # caret stripped for the filename
    assert (tmp_path / "ABC.csv").exists()
    assert out["Close"].tolist() == fetched["Close"].tolist()
