"""Volatility ingestion: ^VXN -> rolling 252-day IV-Rank.

The CBOE Nasdaq-100 Volatility Index (^VXN) is used as an institutional proxy
for TQQQ's option implied vol (TQQQ tracks 3x the Nasdaq-100, and its listed IV
co-moves tightly with ^VXN). We ingest ^VXN's daily close and compute a rolling
252-trading-day IV-Rank:

    IV_Rank = 100 * (IV - min_252) / (max_252 - min_252)

IV-Rank (where today's IV sits in its own 1-year range) is preferred over raw IV
because option richness is relative — a 25% IV is cheap for TQQQ in a crisis and
rich in a calm year.

The pure-math core (:func:`compute_iv_rank`) takes a plain Series so it is fully
unit-testable offline; :func:`fetch_iv_rank_data` is the network wrapper.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_LOOKBACK = 252


def compute_iv_rank(close_iv: pd.Series, lookback: int = DEFAULT_LOOKBACK) -> pd.DataFrame:
    """Compute IV and rolling IV-Rank from a daily implied-vol close series.

    ``close_iv`` is a float Series indexed by date (e.g. ^VXN close, 25.0 == 25%).
    Returns a DataFrame with columns ``IV`` and ``IV_Rank`` (0-100). Rows before
    ``lookback // 2`` observations are dropped (rank undefined during warm-up).
    """
    close_iv = close_iv.astype(float).ffill()
    min_periods = lookback // 2
    roll_min = close_iv.rolling(window=lookback, min_periods=min_periods).min()
    roll_max = close_iv.rolling(window=lookback, min_periods=min_periods).max()

    span = (roll_max - roll_min)
    # Flat window (max == min) -> rank is undefined; treat as mid-range (50).
    iv_rank = ((close_iv - roll_min) / span.where(span != 0)) * 100.0
    iv_rank = iv_rank.where(span != 0, 50.0)

    df = pd.DataFrame({"IV": close_iv, "IV_Rank": iv_rank})
    return df.dropna()


def fetch_iv_rank_data(
    lookback: int = DEFAULT_LOOKBACK,
    start_date: str = "2010-01-01",
    ticker: str = "^VXN",
) -> pd.DataFrame:
    """Download ``ticker`` (default ^VXN) and return IV + rolling IV-Rank.

    Imported lazily so the module (and its unit tests) load without yfinance.
    """
    from ._net import download

    raw = download(ticker, start=start_date, interval="1d")
    if raw is None or raw.empty:
        raise RuntimeError(f"No data returned for {ticker!r}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return compute_iv_rank(raw["Close"], lookback=lookback)


def save_iv_rank_csv(
    out_path: str = "data/tqqq_iv_rank_history.csv",
    lookback: int = DEFAULT_LOOKBACK,
    start_date: str = "2010-01-01",
) -> pd.DataFrame:
    """Fetch and persist the IV-Rank history to CSV, returning the DataFrame."""
    import os

    df = fetch_iv_rank_data(lookback=lookback, start_date=start_date)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    df.to_csv(out_path, index_label="Date")
    return df


if __name__ == "__main__":  # pragma: no cover - manual data refresh
    frame = save_iv_rank_csv()
    print(f"Saved {len(frame)} rows -> data/tqqq_iv_rank_history.csv")
    print(frame.tail())
