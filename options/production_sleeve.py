"""Bridge: the production trend allocation as an overlay-engine weight series.

Lets the options overlay run on top of the *production* trend rule
(`DualSignalAgreement` in `backtest/strat_backtest.py`: ^NDX+^GSPC dual-signal
agreement on SMA200 ± 2.5·ATR, plus an 8%/60d ^GSPC trailing stop) instead of the
overlay's own simpler single-signal sleeve. Feed the result to
``OverlayConfig.external_weight`` to test whether the collar still helps the
strategy the live bot actually runs.

    from options.production_sleeve import production_weight
    w = production_weight(data.index)                  # 0/1 daily allocation
    OptionsOverlayBacktester(OverlayConfig(model="collar", external_weight=w)).run(data)

Requires network (real ^NDX / ^GSPC).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _bull_bear(ticker: str, start: str, end: str | None, atr_mult: float = 2.5):
    """^NDX/^GSPC bullish/bearish (SMA200 ± atr_mult·ATR14) + close. Pure enough to
    reuse the production indicator definitions."""
    from ._net import download

    d = download(ticker, start=start, end=end)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    sma = d["Close"].rolling(200).mean()
    prev = d["Close"].shift(1)
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - prev).abs(),
                    (d["Low"] - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    return d["Close"] > sma + atr_mult * atr, d["Close"] < sma - atr_mult * atr, d["Close"]


def production_weight(index: pd.DatetimeIndex, atr_mult: float = 2.5,
                      trailing_stop_pct: float = 0.08, cooldown_days: int = 60,
                      start: str = "1985-01-01", end: str | None = None) -> pd.Series:
    """Daily 0/1 equity weight from the production dual-signal + trailing-stop rule,
    aligned to ``index``. Reuses ``DualSignalAgreement._apply_trailing_stop`` so the
    stop matches the live bot exactly."""
    from backtest.strat_backtest import DualSignalAgreement

    nb, nbear, _ = _bull_bear("^NDX", start, end, atr_mult)
    gb, gbear, gclose = _bull_bear("^GSPC", start, end, atr_mult)
    R = lambda s: s.reindex(index).ffill().fillna(False)
    nb, nbear, gb, gbear = R(nb), R(nbear), R(gb), R(gbear)

    buy, sell = nb & gb, nbear & gbear
    state = pd.Series(np.nan, index=index)
    state[buy] = 1.0
    state[sell] = 0.0
    init = 1.0 if bool(nb.iloc[0] and gb.iloc[0]) else 0.0
    in_market = state.ffill().fillna(init).shift(1).fillna(init).astype(bool)  # T+1

    dsa = DualSignalAgreement(trailing_stop_pct=trailing_stop_pct,
                              trailing_stop_cooldown_days=cooldown_days)
    df = pd.DataFrame({"in_market": in_market,
                       "Close": gclose.reindex(index).ffill()}, index=index)
    return dsa._apply_trailing_stop(df, price=df["Close"]).astype(float)
