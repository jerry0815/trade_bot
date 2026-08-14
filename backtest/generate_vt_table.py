"""
Generates the VT (global-equities) rolling-backtest table shown in README.md
(Table 9), using the SAME strategy set, leverage tiers, and 26-year rolling
window as Table 2 (S&P 500) — see backtest/generate_readme_tables.py.

    python backtest/generate_vt_table.py

Writes a markdown table to stdout AND backtest/vt_table_output.md. Copy the
rows into README.md by hand (same convention as generate_readme_tables.py:
numbers are machine-generated, prose/commentary stays under human control).

--------------------------------------------------------------------------
Why a splice, and what "VT" means in this table
--------------------------------------------------------------------------
The Vanguard Total World Stock ETF (VT) only began trading in mid-2008, so it
cannot fill the 26-year rolling windows used by Tables 1-3. To make a
comparable long-history table we RECONSTRUCT a synthetic daily series by
return-splicing:

    1985-01 .. 2002       MSCI World price index          (^990100-USD-STRD)
    2003    .. 2008-06    MSCI World + EM sleeve (EEM), market-cap weighted
    2008-07 .. present     real VT daily bars

The pre-2008 proxy is blended with an emerging-markets sleeve (EEM) at a weight
that ramps toward EM's real share of global market cap (0% -> ~12%, see
EM_WEIGHT_BY_YEAR) so the proxy's *composition* matches VT (developed + EM)
rather than developed-only. Validation showed the EM omission was the single
largest source of drift vs real VT; adding it drops the mean annual gap from
~2.1pp to ~0.7pp and the CAGR gap from +0.32% to ~0. The blended series is
scaled by a single constant so it joins VT's price level continuously. It is
still a reconstruction, NOT real VT:

  * For the 1985-2000 window START dates (the same ones Table 2 uses), MOST of
    each 26-year window is the reconstructed proxy, not real VT.
  * EEM's history starts 2003-04, so the EM sleeve is 0 before then. That is
    acceptable because EM was a tiny slice of the world in that era (~1% in the
    late 1980s), so its omission there is a small error.
  * The proxy still omits global SMALL caps (no long history available), so it
    runs marginally hot vs true VT.
  * The MSCI World index has many flat (High==Low) bars in the early years, so
    the SMA-ATR *buffer* is understated in the proxy era. The other four
    strategies (Buy & Hold, EMA, VIX, RSI) do not depend on the intraday range.
  * Like Tables 1-3, this is PRICE return (ex-dividend): raw Close is used for
    all legs and VT, so results are comparable to the other tables but
    understate VT's total (dividend-inclusive) return.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import pandas as pd

from backtest.strat_backtest import DATA_CACHE, get_cached_data
from backtest.generate_readme_tables import run_table

PROXY_TICKER = "^990100-USD-STRD"   # MSCI World price index, daily back to 1985
EM_TICKER    = "EEM"                # iShares MSCI EM ETF (USD, 2003-04+)
REAL_VT      = "VT"                  # Vanguard Total World Stock ETF, 2008-07+
SPLICE_KEY   = "VT_SPLICE"          # cache key the backtest runs against
OUTPUT_PATH  = REPO_ROOT / "backtest" / "vt_table_output.md"

TITLE = ("Table 9: Global Equities (MSCI World + EM → VT splice) "
         "— Lump Sum Performance")

# Emerging-markets weight in the developed+EM proxy, by year. VT (FTSE Global
# All Cap) holds EM; MSCI World does not, and validation showed that omission is
# the single largest source of the proxy's drift vs real VT. So we carve out an
# EM sleeve (EEM) whose weight tracks EM's real share of global equity market
# cap — near-zero in the deep past (EM was ~1% of the world in the late 1980s),
# ramping to ~12% by 2008. EEM's history starts 2003-04, so the weight is forced
# to 0 before then anyway; that is acceptable precisely because EM was a tiny
# slice in that era, so its omission there is a small error. Editable.
EM_WEIGHT_BY_YEAR = {
    2003: 0.05, 2004: 0.06, 2005: 0.07, 2006: 0.09, 2007: 0.11, 2008: 0.11,
}
# Any pre-2003 year (or year absent above) gets 0.0 — see note above.


def _prep(df):
    df = df.copy()
    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]
    # Index series can report null O/H/L on flat days — fill from Close so
    # ATR/True-Range stay finite (True_Range collapses to 0 on those bars).
    for c in ["Open", "High", "Low"]:
        df[c] = df[c].fillna(df["Close"])
    return df


def build_spliced_vt():
    """Build the synthetic 1985+ daily OHLC series and register it in DATA_CACHE
    under SPLICE_KEY, so the backtester runs against it via base_ticker.

    Pre-2008 proxy = MSCI World blended with an EM sleeve (EEM) at a market-cap
    weight that ramps 0% -> ~12% (EM_WEIGHT_BY_YEAR). The blended close-to-close
    path drives a synthetic series; O/H/L are reconstructed by borrowing MSCI
    World's (the dominant leg's) intraday ratios, keeping ATR/execution intact.
    The result is scaled by one constant to join real VT continuously."""
    world = _prep(get_cached_data(PROXY_TICKER))
    em    = _prep(get_cached_data(EM_TICKER))
    vt    = _prep(get_cached_data(REAL_VT))

    cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    splice_date = vt.index[0]
    w = world[world.index < splice_date]
    if w.empty:
        raise RuntimeError(f"No proxy data before VT start {splice_date.date()}.")

    # EM daily returns aligned to the World calendar; missing days contribute 0
    # EM (fall back to World-only for that bar) to avoid fills/lookahead.
    world_ret = w["Close"].pct_change()
    em_ret    = em["Close"].pct_change().reindex(w.index)
    w_em = pd.Series(w.index.year, index=w.index).map(
        lambda y: EM_WEIGHT_BY_YEAR.get(y, 0.0)).astype(float)
    w_em_eff = w_em.where(em_ret.notna(), 0.0)           # no EM data -> weight 0
    blend_ret = ((1 - w_em_eff) * world_ret
                 + w_em_eff * em_ret.fillna(0.0))
    em_active = float((w_em_eff > 0).sum())

    # Synthetic close along the blended path, then borrow World's intraday shape.
    synth_close = (1 + blend_ret.fillna(0.0)).cumprod() * w["Close"].iloc[0]
    pre = pd.DataFrame(index=w.index)
    pre["Close"] = synth_close
    for c in ["Open", "High", "Low"]:
        pre[c] = synth_close * (w[c] / w["Close"])
    pre["Adj Close"] = synth_close
    pre["Volume"] = 0

    # Continuity: single constant so the proxy's last close lands on VT's first.
    k = vt["Close"].iloc[0] / pre["Close"].iloc[-1]
    for c in ["Open", "High", "Low", "Close", "Adj Close"]:
        pre[c] = pre[c] * k

    spliced = pd.concat([pre[cols], vt[cols]]).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="last")]

    DATA_CACHE[SPLICE_KEY] = spliced
    print(f"Spliced VT series: {spliced.index[0].date()} -> {spliced.index[-1].date()} "
          f"({len(spliced)} bars); proxy/real boundary at {splice_date.date()}, "
          f"scale k={k:.4f}; EM sleeve active on {em_active:.0f} pre-2008 bars.")
    return SPLICE_KEY


if __name__ == "__main__":
    print("Building MSCI World -> VT splice...")
    key = build_spliced_vt()
    print(f"\nRunning {TITLE}...")
    out = run_table(TITLE, key)
    print("\n" + out)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"\nWritten to {OUTPUT_PATH}")
