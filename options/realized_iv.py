"""Realized-volatility implied-vol proxy for single-name covered-call studies.

The covered-call income engine writes options against shares the holder already
owns (NVDA, PLTR, TQQQ). No live option chain is assumed, so — as with the
^VXN proxy the overlay uses for TQQQ — implied vol is *modeled* from price
history:

1. :func:`realized_vol` — annualized rolling std of daily log returns.
2. :func:`implied_proxy` — implied ≈ realized × ``vrp_mult`` (single-name IV
   typically runs ~1.1–1.3× trailing realized because of the vol-risk premium;
   default 1.15).

The IV-Rank gate then reuses :func:`options.iv_loader.compute_iv_rank` on the
proxy IV series, so the whole methodology is self-contained per name and needs
only price history (fetched via :func:`options._net.download`, cached to
``data/<TICKER>_history.csv`` like the existing NDX/GSPC/VIX CSVs).

This is a **backtest-grade ranking signal, not tradeable P&L** — the same
caveat class as the overlay docs. The pure-math cores take plain Series so they
are fully unit-testable offline; :func:`load_price_history` is the network
wrapper.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

DEFAULT_WINDOW = 21
TRADING_DAYS = 252
DEFAULT_VRP_MULT = 1.15

# Per-ticker vol-risk-premium overrides (single-name IV / trailing realized).
# PLTR's listed options run richer; TQQQ (already 3x) a touch leaner.
VRP_MULT_BY_TICKER: dict[str, float] = {
    "NVDA": 1.15,
    "PLTR": 1.20,
    "TQQQ": 1.10,
}


def realized_vol(
    close: pd.Series,
    window: int = DEFAULT_WINDOW,
    trading_days: int = TRADING_DAYS,
) -> pd.Series:
    """Annualized rolling realized volatility from a daily close series.

    ``window`` is the rolling lookback in trading days (default 21 ≈ one month).
    Returns an annualized decimal vol Series (0.40 == 40%), aligned to ``close``
    with the warm-up rows dropped. Uses daily *log* returns and the sample std
    (``ddof=1``), scaled by ``sqrt(trading_days)``.
    """
    close = close.astype(float)
    log_ret = np.log(close / close.shift(1))
    rv = log_ret.rolling(window=window, min_periods=window).std(ddof=1) * np.sqrt(trading_days)
    rv.name = "RealizedVol"
    return rv.dropna()


def implied_proxy(realized: pd.Series, vrp_mult: float = DEFAULT_VRP_MULT) -> pd.Series:
    """Model implied vol as ``realized × vrp_mult`` (vol-risk premium).

    ``vrp_mult`` > 1 reflects that sold single-name IV usually trades above
    trailing realized. Returns a decimal-vol Series named ``IV``.
    """
    iv = realized.astype(float) * float(vrp_mult)
    iv.name = "IV"
    return iv


def vrp_mult_for(ticker: str, default: float = DEFAULT_VRP_MULT) -> float:
    """Per-ticker VRP multiplier, falling back to ``default`` for unknown names."""
    return VRP_MULT_BY_TICKER.get(ticker.upper(), default)


def load_price_history(
    ticker: str,
    start: str = "2020-01-01",
    end: str | None = None,
    cache_dir: str = "data",
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch (or load from cache) daily OHLC for ``ticker``.

    Persists ``data/<TICKER>_history.csv`` (Date index + OHLC/Volume columns),
    mirroring the existing NDX/GSPC/VIX CSVs. On a cache hit the CSV is returned
    without touching the network; pass ``refresh=True`` to force a re-download.
    yfinance is imported lazily so this module (and its tests) load without it.
    """
    ticker = ticker.upper()
    cache_path = os.path.join(cache_dir, f"{ticker}_history.csv")

    if not refresh and os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        df.index.name = "Date"
        return _slice(df, start, end)

    from ._net import download

    raw = download(ticker, start=start, end=end, interval="1d")
    if raw is None or raw.empty:
        raise RuntimeError(f"No price data returned for {ticker!r}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.index.name = "Date"

    os.makedirs(cache_dir or ".", exist_ok=True)
    raw.to_csv(cache_path, index_label="Date")
    return _slice(raw, start, end)


def _slice(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start is not None:
        df = df[df.index >= pd.to_datetime(start)]
    if end is not None:
        df = df[df.index <= pd.to_datetime(end)]
    return df


def build_iv_frame(
    close: pd.Series,
    vrp_mult: float = DEFAULT_VRP_MULT,
    window: int = DEFAULT_WINDOW,
) -> pd.DataFrame:
    """Realized vol → proxy IV → rolling IV-Rank, as a single aligned frame.

    Returns a DataFrame with columns ``RealizedVol``, ``IV`` and ``IV_Rank``
    (0-100). Reuses :func:`options.iv_loader.compute_iv_rank` for the rank so the
    gate is identical to the overlay's.
    """
    from .iv_loader import compute_iv_rank

    rv = realized_vol(close, window=window)
    iv = implied_proxy(rv, vrp_mult)
    ranked = compute_iv_rank(iv)  # columns IV, IV_Rank
    out = pd.DataFrame({"RealizedVol": rv})
    out["IV"] = ranked["IV"]
    out["IV_Rank"] = ranked["IV_Rank"]
    return out.dropna()
