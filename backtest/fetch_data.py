"""Download the raw history used by the backtests into the local data/ folder,
so runs read from disk instead of hitting yfinance every time.

Saves one CSV per ticker under data/ (e.g. data/NDX.csv). Re-run any time to
refresh with the latest bars (overwrites existing files).

Usage:
    python backtest/fetch_data.py                # core tickers below
    python backtest/fetch_data.py QQQ TLT        # plus any extra tickers
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import get_cached_data, DATA_DIR

# Tickers the rolling backtests and signals depend on:
#   ^NDX  — NASDAQ-100 (TQQQ base / returns)
#   ^GSPC — S&P 500 (dual-signal confirming ticker + trailing-stop reference)
#   ^VIX  — volatility index (VIX column used by prep_base_indicators)
CORE_TICKERS = ["^NDX", "^GSPC", "^VIX"]


def main(extra):
    tickers = CORE_TICKERS + [t.upper() for t in extra]
    print(f"Downloading {len(tickers)} ticker(s) into {DATA_DIR}\n")
    for t in tickers:
        try:
            df = get_cached_data(t, refresh=True)  # force download + write CSV
            lo, hi = df.index.min(), df.index.max()
            print(f"  {t:<7} {len(df):>6} rows  {lo.date()} -> {hi.date()}  "
                  f"[{DATA_DIR.name}/{t.replace('^','')}.csv]")
        except Exception as e:  # noqa: BLE001 - report and continue to next ticker
            print(f"  {t:<7} FAILED: {e}")
    print("\nDone. Backtests will now read these from disk (no re-download).")


if __name__ == "__main__":
    main(sys.argv[1:])
