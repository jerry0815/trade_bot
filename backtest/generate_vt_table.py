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

    1985-01 .. 2008-06   MSCI World price index  (^990100-USD-STRD)
    2008-07 .. present    real VT daily bars

The pre-2008 proxy is scaled by a single constant so it joins VT's price level
continuously at the splice date; this preserves the proxy's daily returns
exactly and just rebases the price level. The result is therefore best read as
a "MSCI World -> VT splice", NOT as real VT:

  * For the 1985-2000 window START dates (the same ones Table 2 uses), MOST of
    each 26-year window is the MSCI World proxy, not real VT.
  * MSCI World is DEVELOPED markets only; VT (FTSE Global All Cap) also holds
    emerging markets and small caps. Close cousins, not identical.
  * The MSCI World index has many flat (High==Low) bars in the early years, so
    the SMA-ATR *buffer* is understated in the proxy era. The other four
    strategies (Buy & Hold, EMA, VIX, RSI) do not depend on the intraday range.
  * Like Tables 1-3, this is PRICE return (ex-dividend): raw Close is used for
    both the MSCI World price index and VT, so results are comparable to the
    other tables but understate VT's total (dividend-inclusive) return.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import pandas as pd

from backtest.strat_backtest import DATA_CACHE, get_cached_data
from backtest.generate_readme_tables import run_table

PROXY_TICKER = "^990100-USD-STRD"   # MSCI World price index, daily back to 1985
REAL_VT      = "VT"                  # Vanguard Total World Stock ETF, 2008-07+
SPLICE_KEY   = "VT_SPLICE"          # cache key the backtest runs against
OUTPUT_PATH  = REPO_ROOT / "backtest" / "vt_table_output.md"

TITLE = ("Table 9: Global Equities (MSCI World → VT splice) "
         "— Lump Sum Performance")


def build_spliced_vt():
    """Build the synthetic 1985+ daily OHLC series and register it in DATA_CACHE
    under SPLICE_KEY, so the backtester runs against it via base_ticker."""
    proxy = get_cached_data(PROXY_TICKER).copy()
    vt    = get_cached_data(REAL_VT).copy()

    cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    for df in (proxy, vt):
        if "Adj Close" not in df.columns:
            df["Adj Close"] = df["Close"]
        # Index series can report null O/H/L on flat days — fill from Close so
        # ATR/True-Range stay finite (True_Range collapses to 0 on those bars).
        for c in ["Open", "High", "Low"]:
            df[c] = df[c].fillna(df["Close"])

    splice_date = vt.index[0]
    pre = proxy[proxy.index < splice_date]
    if pre.empty:
        raise RuntimeError(f"No proxy data before VT start {splice_date.date()}.")

    # Continuity: scale the whole proxy segment so its last close lands exactly
    # on VT's first close. Single constant => daily returns are preserved.
    k = vt["Close"].iloc[0] / pre["Close"].iloc[-1]
    pre_scaled = pre.copy()
    for c in ["Open", "High", "Low", "Close", "Adj Close"]:
        pre_scaled[c] = pre_scaled[c] * k
    pre_scaled["Volume"] = 0

    spliced = pd.concat([pre_scaled[cols], vt[cols]]).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="last")]

    DATA_CACHE[SPLICE_KEY] = spliced
    print(f"Spliced VT series: {spliced.index[0].date()} -> {spliced.index[-1].date()} "
          f"({len(spliced)} bars); proxy/real boundary at {splice_date.date()}, "
          f"scale k={k:.4f}")
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
