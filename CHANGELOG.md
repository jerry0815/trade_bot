# Changelog

All notable changes to this project are documented here.

---

## [2026-07-22] — Feature: T+2 Confirmation Delay & Strategy Optimization Analysis

### New Feature: T+2 Signal Confirmation (`strat_backtest.py`, `bot.py`)
- **T+2 Mechanism**: Added `t2_confirmation` parameter to `SMATrendFollowing`. When enabled, buy/sell signals must persist for two consecutive trading days (`rolling(window=2).min() == 1`) before executing a state change. This prevents "whipsaw" false signals from triggering trades on a single day of high volatility.
- **Bot Output**: Updated `bot.py` to display the exact upper and lower ATR bounds so that it is clear when price approaches a threshold. Also added a `Pending SELL/BUY` warning that displays on the first day of a trend change while waiting for the T+2 confirmation.
- **Ablation Study**: Conducted a 20-year ablation study on ATR bounds (14 vs 50) and defensive asset holds (Cash vs KMLM+SGOV). Concluded that T+2 confirmation alone offers the best risk-adjusted performance boost while a 50-day ATR and managed futures blend underperformed the baseline.

---
## [2026-07-22] — Bug Fix: yfinance SQLite Database Locking

### Bug Fix: `OperationalError` on yfinance Rate-Limit (`strat_backtest.py`)
- **Root cause:** yfinance downloads multiple tickers simultaneously using threads by default. It relies on an internal SQLite cache (via `requests_cache`), which can occasionally throw `OperationalError('database is locked')` when concurrent threads try to access it simultaneously on GitHub runners.
- **Fix:** Added `threads=False` to the `yf.download` call in `_download_with_retry` to prevent concurrent database writes.
- **Fix:** Wrapped the `yf.download` call in a `try...except Exception` block to catch `OperationalError` and other unexpected exceptions. This ensures the script doesn't crash on transient errors but instead moves gracefully into the exponential back-off retry loop.

---

## [2026-07-14] — Rate-Limit Resilience & Download Refactor

### Bug Fix: `IndexError` on yfinance Rate-Limit (`strat_backtest.py`)
- **Root cause:** Yahoo Finance rate-limits GitHub Actions runners (shared IPs used by many projects).
  When rate-limited, `yf.download` silently returns an empty DataFrame. The subsequent `.iloc[-1]`
  call on an empty Series raised `IndexError: single positional indexer is out-of-bounds`, masking
  the true cause.
- **Fix:** Added a module-level `_download_with_retry(tickers, period, max_retries=5)` helper that
  retries the download up to 5 times with exponential back-off (15 s → 30 s → 60 s → 120 s).
- **Fix:** Added a per-ticker empty-DataFrame guard after slicing the MultiIndex result. Raises a
  descriptive `RuntimeError` naming the missing tickers instead of the cryptic `IndexError`.

### Refactor: Single Shared Download (`bot.py` + `strat_backtest.py`)
- `generate_market_report` previously triggered **two** separate `yf.download` calls (one for the
  NDX signal, one for the S&P 500 signal), doubling rate-limit exposure on every run.
- Refactored to perform **one combined download** — `"QQQ TQQQ SPY ^VIX"` — at the top of
  `generate_market_report` and pass the resulting DataFrame to both `get_live_stats` calls via a
  new optional `data=` parameter.
- `BaseStrategy.get_live_stats` and `SMATrendFollowing.get_live_stats` both accept `data=None`;
  when `data` is supplied the download step is skipped entirely. Standalone callers that omit
  `data` continue to work unchanged.
- `_download_with_retry` exported from `strat_backtest` and imported in `bot.py`.

### Code Quality
- Renamed local variable `tqqq` → `leveraged_df` in `BaseStrategy.get_live_stats` — the leveraged
  ticker is not always TQQQ (e.g. the S&P 500 call passes `"SPY"`).
- Renamed returned dict key `"tqqq_price"` → `"leveraged_price"` for the same reason; updated
  the corresponding reference in `bot.py`.

---

## [2026-07-12] — Cross-Signal Backtesting

### New Feature: `signal_ticker` Parameter
- Added `signal_ticker` parameter to `Backtester`, `RollingBacktester`, and `run_experiment_suite`.
- When `signal_ticker` differs from `base_ticker`, the strategy generates `in_market` signals from the
  signal ticker's price/indicator data, but portfolio returns are computed from the base ticker's daily moves.
- Enables experiments such as *"trade TQQQ (3x NDX exposure) using S&P 500 trend signals"*:
  ```python
  Backtester(base_ticker="^NDX", signal_ticker="^GSPC", leverage=3)
  RollingBacktester(base_ticker="^NDX", signal_ticker="^GSPC", ...)
  run_experiment_suite(..., base_ticker="^NDX", signal_ticker="^GSPC")
  ```
- Both caches are pre-warmed before parallel threads launch in `RollingBacktester.run()`.
- Dates with no data in the return ticker are dropped automatically (handles different listing histories).

### Experiment Results: NDX 3x — Own Signal vs GSPC Signal (SMA 200, ATR x2.5)
*171 rolling 26-year windows, 1986-04-29 to 2000-06-28*

| Leverage | Setup | Avg TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: |
| 3x | NDX own signal | 23.57% | 10.53% | -81.38% | 14.9 |
| 3x | **NDX + GSPC signal** | **23.59%** | **12.04%** | -83.79% | **11.7** |
| 2x | NDX own signal | 20.71% | 10.96% | -62.51% | 14.9 |
| 2x | NDX + GSPC signal | 20.37% | 11.62% | -64.66% | 11.7 |
| 1x | NDX own signal | 13.95% | 8.48% | -35.77% | 14.9 |
| 1x | NDX + GSPC signal | 13.64% | 8.64% | -35.77% | 11.7 |

Key finding: GSPC signal on NDX produces nearly identical returns at 3x (+0.02% avg TWR) with ~3 fewer
trades per period and a higher worst-case floor (12.04% vs 10.53%). Slightly worse worst drawdown
(-83.79% vs -81.38%) because GSPC exits later when NDX crashes faster than the broader market.

---

## [2026-07-11] — Engine Overhaul & Code Quality

### Execution Model
- **Next-day open execution:** Orders now execute at the *following day's open*, not the signal day's close.
  Entry days earn the open→close return at leverage; exit days capture only the overnight gap at leverage.
  This eliminates look-ahead bias that existed in the original same-day execution model.

### Performance & Architecture
- **Vectorised portfolio math:** `_run_portfolio_math` now pre-computes the full daily-return array as a
  single NumPy vectorised pass before the scalar accounting loop. Eliminates `itertuples` and per-row
  Python branching — significant speedup for long histories.
- **Parallel rolling backtests:** `RollingBacktester` uses `ThreadPoolExecutor` (up to 8 workers).
  The signal cache is pre-warmed before threads launch so all workers read-only — no concurrent downloads.
- **Concurrent live data fetch:** `get_live_stats` downloads all 3 tickers (monitor, leveraged, VIX)
  simultaneously via a thread pool, ~3x faster than sequential `yf.download` calls.

### Tax Simulation
- Added `apply_tax` parameter to `Backtester` and `run_experiment_suite`.
- When enabled, US capital gains tax is deducted on each realised gain at exit:
  - **Long-term (>365 days held):** 15%
  - **Short-term (<=365 days held):** 25%
- Tax drag is reflected in both the final portfolio value and the after-tax TWR.
- Per-trade log entries include `tax_paid` and `tax_type` fields.
- Global rate constants `TAX_LONG_TERM_RATE` and `TAX_SHORT_TERM_RATE` at the top of `strat_backtest.py`.

### TWR Accuracy
- TWR is now annualised using **actual trading days** (`twr_index ** (252 / len(df))`) rather than the
  configured `period_years`. More accurate for partial periods and data gaps, especially in rolling backtests.

### Configurable Metric Key
- `RollingBacktester.__init__` now accepts `metric_key` (default `"strategy_twr"`) and `metric_label`
  (default `"TWR"`), allowing rolling comparisons to rank by any result field such as `"final_value"` or
  `"max_drawdown"`.

### Cache Management
- Added `cache_clear()` top-level function that flushes both `DATA_CACHE` and `SIGNAL_CACHE`.
  Call when changing indicator parameters not covered by the cache key (e.g. ATR period, borrow rate table),
  or to force a fresh `yfinance` download after market close.

### Live Signal — Position Duration
- `get_live_stats` now returns `days_in_current_state` and `state_since` fields.
- Discord/console report shows how many consecutive trading days the strategy has been in the current
  state (invested or cash) and the calendar date that streak started.

### Bug Fixes
- Fixed `f.result()` called twice inside `RollingBacktester.run()` list comprehension — results are now
  collected in one pass (`raw = [f.result() for f in futures]`) then filtered.
- Fixed `SMATrendFollowing._add_indicator_logic` silently using wrong SMA when `sma_window != 200` —
  SMA is now always recomputed from `self.sma_window`.
- Fixed `_calculate_trade_stats` counting trades from the full data history instead of the sliced test
  period, causing inflated trade counts.
- Replaced `raw_signal.shift(1) == True` with `np.where(shifted.isna(), False, shifted).astype(bool)`
  in `VolatilityFilter`, `EMACrossover`, and `RSIMeanReversion` — correct NaN handling and eliminates
  a pandas `FutureWarning` about object-dtype downcasting.
- Fixed stale step numbering comment in `Backtester.run()` (was 1→2→2→3→4, now 1→2→3→4→5).
- `signal_changed.txt` in `bot.py` is now only written when the signal actually flips, so the file's
  mtime is a reliable change indicator.

### Dead Code Removed
- Removed `calculate_signal()` from `bot.py` (35-line duplicate of strategy logic, never called).
- Removed orphan `_get_data()` from `Backtester` (replaced by `get_cached_data()`).
- Removed broken `get_report_fields()` override from `RSIMeanReversion`.
- Removed dead `if "cash_log" in final_results: del ...` guard from `Backtester.run()`.
- Removed unused `total_trades` accumulation inside `generate_signals()` (double-counted old trades).

### Import Cleanup (`bot.py`)
- Replaced `from backtest.strat_backtest import *` with explicit `from backtest.strat_backtest import SMATrendFollowing`.
- Removed unused `import yfinance as yf` and `import datetime`.

---

## [2026-07-10] — Initial Release

- `Backtester` engine with SMA 200 + ATR buffer strategy.
- `RollingBacktester` for multi-period analysis.
- Discord webhook integration via `bot.py`.
- GitHub Actions workflow for daily automated reporting.
