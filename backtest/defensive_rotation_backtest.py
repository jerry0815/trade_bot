"""Proxy-extended backtest of the defensive rotation.

`bot.py`'s `get_current_defensive_rotation` holds the strongest 126-day-momentum
of KMLM / TLT / GLD / SHY when out of TQQQ. The real ETFs are short-lived (KMLM
from 2020), so this module splices each onto a longer mutual-fund / futures proxy,
validates the proxy against the real ETF, and backtests "out = rotation" vs
"out = cash" over the production trend allocation.

Honest limits: managed futures (KMLM) has no proxy before 2007 and RYMTX tracks
KMLM only loosely (daily-return corr ~0.54), so the 4-asset result is evidence-
limited. See `docs/strategies/defensive-rotation.md`. Requires network.

    python -m backtest.defensive_rotation_backtest
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# real ETF -> longer-history proxy
PROXY = {"TLT": "VUSTX", "GLD": "GC=F", "SHY": "VFISX", "KMLM": "RYMTX"}
MOMENTUM_LOOKBACK = 126
CASH_YIELD = 0.045


def _close(ticker: str, index: pd.DatetimeIndex) -> pd.Series:
    from options._net import download
    d = download(ticker, start="1985-01-01", end=None)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    return d["Close"].reindex(index)


def spliced_prices(assets, index) -> tuple[pd.DataFrame, dict]:
    """Return (spliced total-return price per asset, {asset: proxy-vs-real corr})."""
    out, val = {}, {}
    for a in assets:
        real, prox = _close(a, index), _close(PROXY[a], index)
        rr, pr = real.pct_change(), prox.pct_change()
        ov = rr.notna() & pr.notna()
        val[a] = float(np.corrcoef(rr[ov], pr[ov])[0, 1]) if ov.sum() > 2 else float("nan")
        combined = rr.where(rr.notna(), pr)                 # real where available, else proxy
        out[a] = (1 + combined.fillna(0)).cumprod().where(combined.notna().cummax())
    return pd.DataFrame(out), val


def rotation_returns(px: pd.DataFrame) -> pd.Series:
    """Daily return of holding the best trailing-momentum asset (winner from
    yesterday's 126-day momentum — no lookahead)."""
    mom = (px / px.shift(MOMENTUM_LOOKBACK) - 1).shift(1)
    rets = px.pct_change()
    winner = mom.idxmax(axis=1)
    dr = pd.Series(0.0, index=px.index)
    for a in px.columns:
        dr[winner == a] = rets[a][winner == a]
    return dr.fillna(0.0)


def _metrics(ret: pd.Series) -> tuple[float, float, float]:
    nav = (1 + ret).cumprod()
    yrs = (ret.index[-1] - ret.index[0]).days / 365.25
    cagr = (nav.iloc[-1] ** (1 / yrs) - 1) * 100
    mdd = (nav / nav.cummax() - 1).min() * 100
    sharpe = (ret.mean() - CASH_YIELD / 252) / ret.std() * np.sqrt(252)
    return cagr, mdd, sharpe


def run(assets, start: str, in_market: pd.Series, tqqq_ret: pd.Series):
    """Compare out=cash vs out=rotation over the production allocation."""
    px, val = spliced_prices(assets, in_market.index)
    dr = rotation_returns(px)
    mask = (in_market.index >= pd.Timestamp(start)) & px.notna().all(axis=1)
    cash_daily = CASH_YIELD / 252
    base = pd.Series(np.where(in_market, tqqq_ret, cash_daily), index=in_market.index)[mask]
    rot = pd.Series(np.where(in_market, tqqq_ret, dr), index=in_market.index)[mask]
    return {"validation": val, "window": (base.index[0], base.index[-1]),
            "out_share": float((~in_market[mask]).mean()),
            "cash": _metrics(base), "rotation": _metrics(rot)}


def main():  # pragma: no cover - network + long-running
    from options.reconstruct_tqqq import prepare_extended_data
    from options.production_sleeve import production_weight

    data = prepare_extended_data(start="1990-01-01", end=None)
    in_market = production_weight(data.index) > 0
    tqqq_ret = data["Close"].pct_change().fillna(0)

    for assets, start, label in [
        (["TLT", "GLD", "SHY"], "2000-09-01", "3-asset (bonds/gold/cash) — proxy to 2000"),
        (["KMLM", "TLT", "GLD", "SHY"], "2007-04-01", "4-asset incl managed futures — proxy to 2007"),
    ]:
        r = run(assets, start, in_market, tqqq_ret)
        print(f"\n== {label}  ({r['window'][0].date()}..{r['window'][1].date()}, "
              f"out {r['out_share']*100:.0f}% of days) ==")
        print("  proxy corr: " + ", ".join(f"{a} {c:.2f}" for a, c in r["validation"].items()))
        for tag in ("cash", "rotation"):
            cg, md, sh = r[tag]
            print(f"  out = {tag:9} CAGR {cg:6.1f}  MDD {md:7.1f}  Sharpe {sh:5.2f}")


if __name__ == "__main__":  # pragma: no cover
    main()
