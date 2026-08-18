"""Reconstruct a synthetic TQQQ back to before its 2010 inception.

Real TQQQ starts 2010-02-11, so it never lived through the dot-com crash or 2008.
TQQQ is a 3x-daily Nasdaq-100 ETF, so we can rebuild it from ^NDX (history to
1985): each day compounds ``3 * r_ndx`` minus the fund's drag (0.95% expense +
financing on the 2x borrowed notional at the short rate), plus a single calibrated
constant that absorbs the 3x dividend yield and tracking (the index is price-only).

The reconstruction is **validated against real TQQQ over 2010-2026** (daily-return
correlation ~0.999); the calibration constant is fit on that window and then used
pre-2010. Absolute levels compounded over 25 years are frictionless artifacts —
trust the path, drawdowns, and cross-strategy comparison, not the ending dollars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EXPENSE_RATIO = 0.0095   # TQQQ annual expense
BORROW_MULT = 2.0        # 3x exposure borrows 2x notional
LEVERAGE = 3.0
TRADING_DAYS = 252


def synthetic_returns(
    r_ndx: pd.Series,
    short_rate: pd.Series,
    alpha_daily: float = 0.0,
    leverage: float = LEVERAGE,
    expense: float = EXPENSE_RATIO,
    borrow_mult: float = BORROW_MULT,
) -> pd.Series:
    """Daily synthetic TQQQ return. Pure/offline-testable.

    ``short_rate`` is the annualized financing rate (e.g. 13-week T-bill as a
    fraction). Drag = (expense + borrow_mult * short_rate) / 252.
    """
    drag = (expense + borrow_mult * short_rate) / TRADING_DAYS
    return leverage * r_ndx - drag + alpha_daily


def calibrate_alpha(r_syn_raw: pd.Series, real_close: pd.Series) -> float:
    """Constant daily add-on so the synthetic's total return matches real TQQQ
    over their overlap (absorbs the 3x dividend yield the price index omits)."""
    syn = (1 + r_syn_raw.fillna(0)).cumprod()
    common = real_close.index.intersection(syn.index)
    if len(common) < 2:
        return 0.0
    real_g = real_close.reindex(common).iloc[-1] / real_close.reindex(common).iloc[0]
    syn_g = syn.reindex(common).iloc[-1] / syn.reindex(common).iloc[0]
    return float(np.log(real_g / syn_g) / len(common))


def reconstruct_ohlc(
    ndx: pd.DataFrame, short_rate: pd.Series, real_tqqq: pd.DataFrame
) -> pd.DataFrame:
    """Full synthetic TQQQ OHLC. Intraday range = 3x the index's daily excursions;
    level is anchored to real TQQQ at its inception."""
    r_ndx = ndx["Close"].pct_change()
    raw = synthetic_returns(r_ndx, short_rate.reindex(ndx.index).ffill().fillna(0))
    alpha = calibrate_alpha(raw, real_tqqq["Close"])
    r_syn = raw + alpha

    close = (1 + r_syn.fillna(0)).cumprod()
    anchor_idx = close.loc[real_tqqq.index[0]:].index[0]
    close = close / close.loc[anchor_idx] * float(real_tqqq["Close"].iloc[0])
    hi = close * (1 + LEVERAGE * (ndx["High"] / ndx["Close"] - 1))
    lo = close * (1 + LEVERAGE * (ndx["Low"] / ndx["Close"] - 1))
    out = pd.DataFrame({
        "Close": close,
        "High": np.maximum(hi, close),
        "Low": np.minimum(lo, close),
    }).dropna()
    out.attrs["alpha_daily"] = alpha
    return out


def prepare_extended_data(start: str = "2001-06-01", end: str | None = None,
                          sma_period: int = 200) -> pd.DataFrame:
    """Strategy-ready daily frame on reconstructed TQQQ, with ^VXN (→^VIX before
    2001) as the vol proxy. Requires network (yfinance). Mirrors the columns of
    ``run_benchmark.prepare_overlay_data``."""
    from ._net import download
    from .iv_loader import compute_iv_rank

    ndx = download("^NDX", start="1985-01-01", end=end)
    irx = download("^IRX", start="1985-01-01", end=end)      # 13-week T-bill, percent
    vxn = download("^VXN", start="1985-01-01", end=end)
    vix = download("^VIX", start="1985-01-01", end=end)
    real = download("TQQQ", start="2010-01-01", end=end)
    for f in (ndx, irx, vxn, vix, real):
        if isinstance(f.columns, pd.MultiIndex):
            f.columns = f.columns.get_level_values(0)

    short_rate = irx["Close"] / 100.0
    syn = reconstruct_ohlc(ndx, short_rate, real)

    vol = vxn["Close"].reindex(syn.index)
    vol = vol.fillna(vix["Close"].reindex(syn.index) * 1.15)  # VXN ran ~1.1-1.2x VIX

    def _atr(d, p=14):
        pc = d["Close"].shift(1)
        tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(),
                        (d["Low"] - pc).abs()], axis=1).max(axis=1)
        return tr.rolling(p, min_periods=p).mean()

    def _rsi(c, p=14):
        d = c.diff()
        g = d.clip(lower=0).rolling(p, min_periods=p).mean()
        l = (-d.clip(upper=0)).rolling(p, min_periods=p).mean()
        return 100 - 100 / (1 + g / l.replace(0, np.nan))

    df = pd.DataFrame(index=syn.index)
    df["Close"], df["High"], df["Low"] = syn["Close"], syn["High"], syn["Low"]
    df["SMA"] = syn["Close"].rolling(sma_period, min_periods=sma_period).mean()
    df["ATR"] = _atr(syn)
    df["RSI"] = _rsi(syn["Close"])
    iv = compute_iv_rank(vol.dropna())
    df["IV"] = iv["IV"].reindex(df.index).ffill()
    df["IV_Rank"] = iv["IV_Rank"].reindex(df.index).ffill()

    df = df.dropna(subset=["Close", "SMA", "ATR", "IV"])
    df = df[df.index >= pd.to_datetime(start)]
    if end is not None:
        df = df[df.index <= pd.to_datetime(end)]
    df.attrs["alpha_daily"] = syn.attrs.get("alpha_daily", 0.0)
    return df
