# Changelog

All notable changes to this project are documented here.

---

## [2026-07-28] — Feature: Signal & Parameter Sweep + Published Table 4

### New Feature: `EMACrossover` ATR Buffer & T+2 Confirmation (`strat_backtest.py`)
- Added opt-in `atr_multiplier` and `t2_confirmation` parameters to `EMACrossover`, mirroring the options
  `SMATrendFollowing` already had. Both default to off (`atr_multiplier=None`, `t2_confirmation=False`),
  so existing `EMACrossover()` callers — including Tables 1-3's default rows and `bot.py` — are unaffected.
  When `atr_multiplier` is set, EMA crossovers must clear an ATR-scaled dead-zone around the crossover
  point before a state change fires; `t2_confirmation` behaves identically to `SMATrendFollowing`'s.

### Refactor: Shared Rolling-Backtest Helpers (`strat_backtest.py`)
- Extracted `warmup_aware_start_dates(tickers, period_years)` and
  `summarize_rolling_results(df_res, strategies, metric_label="TWR")` out of `generate_readme_tables.py`
  into `strat_backtest.py` so both the existing table generator and the new sweep script below share one
  implementation instead of duplicating the warmup-date and summary-statistics logic.

### New Script: `backtest/generate_signal_comparison.py`
- Added a script that runs a 44-variant rolling-26-year sweep at 3x leverage on `^NDX`: 20 SMA
  combinations (ATR in {1.5, 2.0, 2.5, 3.0, 3.5} x signal in {own ^NDX, S&P 500} x T+2 in {off, on}) and
  24 EMA combinations (the same grid plus a no-ATR baseline). Mechanically picks a "best real-world
  practice" combination as the highest Avg TWR among the 33 variants remaining after excluding the 11
  deepest-drawdown variants (worst quartile) out of all 44 — a rule, not a subjective call. Writes both
  sweep tables and the pick to `backtest/signal_comparison_output.md` (gitignored) for hand-copying into
  the README, following the same generate-then-transcribe pattern as `generate_readme_tables.py`.

### Docs: Published README Table 4 (`README.md`)
- Added "Table 4: 3x TQQQ — Signal & Parameter Comparison (SMA vs EMA)", fixing leverage at 3x and
  sweeping the parameters Tables 1-3 never varied. The mechanical Best Practice pick: **SMA 200, ATR x3.0,
  Signal = Own (^NDX), T+2 = Off** — 24.53% Avg TWR, -83.08% Worst DD, 12 Avg Trades. `bot.py`'s actual
  live configuration is `SMATrendFollowing(sma_window=200, t2_confirmation=True)` (default
  `atr_multiplier=2.5`) with `RECOMMENDED ACTION` driven entirely by the S&P 500 signal
  (`stats_sp500`, `bot.py:78`) — i.e. the **`x2.5 | S&P 500 (^GSPC) | On`** row, 21.77% Avg TWR,
  -83.40% Worst DD. The Best Practice pick beats that real baseline by +2.76pp Avg TWR with an
  essentially flat Worst DD (-0.32pp shallower). An earlier draft of this entry compared against the
  `x2.5 | Own (^NDX) | On` row (23.33%) instead — that was the wrong baseline, since it silently assumes
  a signal-source switch `bot.py` doesn't currently make. Adopting the Best Practice pick would require
  switching `bot.py`'s primary signal source from S&P 500 to NASDAQ-100/own-signal, not just retuning
  `atr_multiplier`/`t2_confirmation`.
- Key findings from the sweep, cited with specific row numbers in the table's commentary: an ATR dead-zone
  never helps EMA at 3x (every ATR-bearing EMA row has a deeper drawdown than every ATR-free row, and none
  beats the ATR-free rows' best Avg TWR); the S&P 500 signal isn't a robust win for either family holding
  ^NDX as the traded asset (SMA splits 4-6 in favor of the own-signal, EMA favors the own signal 11 of 12
  matched pairs); and T+2 confirmation is a net negative for SMA at 3x (helps only 2 of 10 matched pairs,
  both at the tightest ATR band) and roughly a coin flip for EMA (5 of 12 pairs).

---

## [2026-07-28] — Docs: Backtest Results Refresh & Rolling-Window Fix

### Bug Fix: Rolling Windows Shorter Than the Requested Period (`strat_backtest.py`)
- **Root cause:** `Backtester.run()` only rejected a rolling window if the sliced dataframe was completely empty. A window whose nominal start date predated a ticker's actual data history (e.g. requesting a 26-year window starting 1980 when `^NDX`/`^GSPC` data only goes back to 1985) silently truncated instead of being rejected, mixing 20-26 year windows into statistics that assumed a uniform 26-year period.
- **Fix:** Added a check in `Backtester.run()` rejecting any window whose actual data span is less than 98% of the requested `period_years`.

### New Script: `backtest/generate_readme_tables.py`
- Added a script that regenerates the three rolling-backtest tables in `README.md` from the current strategy configuration. Run manually after any change to strategy logic that should be reflected in the published results; writes to `backtest/readme_tables_output.md` (gitignored) for hand-copying into the README.

### Bug Fix: Start-Date Generation & Worst-DD Metric in `generate_readme_tables.py` (post-review)
A final whole-branch review of the refresh above caught two correctness bugs in the new script before the tables it produced were trustworthy:
- **Root cause 1 (window dates):** `monthly_start_dates()` hardcoded `start="1980-01-15"` for all three tables and relied solely on `Backtester.run()`'s 98%-tolerance check to filter bad windows. Because that tolerance is *relative* (2% of 26 years ≈ 190 days of slack), it still let windows start up to ~190 days before a ticker's real data existed, contradicting the README's own claim that windows start "from the earliest available data." **Fix:** restored the warmup-aware formula already proven in the notebook (`max(ticker start dates) + 210 calendar days`, matching the 200-day SMA/EMA indicator warmup), driven per-table by the ticker(s) that table actually needs (both base and signal ticker for Table 3's cross-signal case).
- **Root cause 2 (Worst DD):** `summarize()` computed "Worst DD" as the drawdown *of the worst-TWR window* (`df_res.loc[df_res[ret_col].idxmin(), dd_col]`) rather than the deepest drawdown observed across all windows — silently understating each strategy's true worst drawdown and disagreeing with the engine's own convention in `run_experiment_suite`. **Fix:** compute Worst DD as its own independent minimum (`df_res[dd_col].min()`).
- Also added: acceptance-rate logging per leverage tier (candidate vs. accepted window counts), a guard against a `None`-crash if every tier returns empty, and made the script's `sys.path`/output-path handling independent of the current working directory.
- Tables 1-3 were regenerated again after these fixes. Window sets landed back at the historically-expected ranges (Table 1/3: 1986-04-29 to 2000-07-28, 172 windows; Table 2: 1985-07-31 to 2000-07-28, 181 windows) with 100% window acceptance at every tier — confirming the prior 1980-start numbers had been admitting invalid windows.

### Docs: Regenerated README Backtest Tables (`README.md`)
- Tables 1-3 and their commentary were regenerated using `SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)` — the same configuration `bot.py` runs live — replacing stale numbers from before T+2 confirmation existed, then regenerated again after the window-date and Worst-DD fixes above. Added a note on T+2 confirmation to the "Strategy Logic" section and a third "Triple-Filter" bullet in "Strategy Research & Theoretical Basis" so the documented rules match both the live bot and the backtest.
- Notable findings from the refresh: with T+2 confirmation, EMA 50/200 now outperforms SMA 200 (ATR x2.5) on the S&P 500 signal (Table 2) — a reversal from the pre-T+2 numbers, where SMA led — and the same EMA lead on average/median/worst-case TWR now also shows up in Table 3 (NDX returns on a GSPC signal) at every leverage tier. On the NASDAQ-100 signal (Table 1), SMA 200 isn't an outright winner — EMA actually posts the higher average TWR at every tier — but SMA's consistently shallower drawdown at every tier is what keeps it the preferred, better risk-adjusted choice there.
- Softened Table 2's causal claim about the T+2 delay costing SMA more than it saves in avoided whipsaws — it's a plausible read, but the before/after comparison isn't a controlled same-window ablation (the window set itself also changed), so the README now says so explicitly.

### Docs: Notebook Sync Completed (`backtest/TQQQ_Trend_Strategy_Simulator.ipynb`)
- The initial refresh updated 4 of 5 `SMATrendFollowing()` constructions in the notebook to pass `t2_confirmation=True`; the review caught the 5th (in the "Advanced: Configurable Metric & Tax Comparison" cell), which was fixed along with the hardcoded result-column names in that same cell (the strategy's display name changes to include `[T+2]` once the flag is set).

### Cleanup
- Removed 5 stale/broken or accidental files that were no longer part of any workflow: `run_rolling_comparison.py`, `test_defensive_options.py`, `test_short_strategy.py`, `analyze_covid.py` (stale scripts), and `bot_history.txt` (an accidental UTF-16 `git log -p` text dump, not a script).

---

## [2026-07-23] — Feature: Dynamic Defensive Rotation Reporting

### New Feature: Dynamic Rotation (`bot.py`, `strat_backtest.py`)
- **Momentum-Based Selection**: Added a live absolute momentum calculator (`get_current_defensive_rotation`) to evaluate KMLM (Managed Futures), TLT (Long-Term Bonds), GLD (Gold), and SHY (Short-Term Treasuries). It calculates a rolling 126-day (6-month) momentum for each asset.
- **Discord Bot Update**: Upgraded the bot's "ASSET ALLOCATION" section. The bot now explicitly tells you which defensive asset has the highest momentum (the "winner") and should be held during a sell signal. It displays the live percentages for all four assets, and also explicitly labels `SHY` as `SHY / SGOV` to remind users that ultra-short T-Bills serve the exact same purpose as cash.

---

## [2026-07-22] — Feature: T+2 Confirmation Delay & Strategy Optimization Analysis

### New Feature: T+2 Signal Confirmation (`strat_backtest.py`, `bot.py`)
- **T+2 Mechanism**: Added `t2_confirmation` parameter to `SMATrendFollowing`. When enabled, buy/sell signals must persist for two consecutive trading days (`rolling(window=2).min() == 1`) before executing a state change. This prevents "whipsaw" false signals from triggering trades on a single day of high volatility.
- **Bot Output**: Updated `bot.py` to display the exact upper and lower ATR bounds so that it is clear when price approaches a threshold. Also added a `Pending SELL/BUY` warning that displays on the first day of a trend change while waiting for the T+2 confirmation.
- **Ablation Study**: Conducted a 20-year ablation study on ATR bounds (14 vs 50) and defensive asset holds (Cash vs KMLM+SGOV). Concluded that T+2 confirmation alone offers the best risk-adjusted performance boost while a 50-day ATR and managed futures blend underperformed the baseline.

---

## [2026-07-26] — Bot Reporting Enhancements

### Feat: ATR Channel Bounds in Discord Report (`bot.py` & `strat_backtest.py`)
- **Enhancement:** The daily Discord report now explicitly displays the numerical upper and lower bounds of the ATR channel.
- Updated `bot.py`'s `format_signal_section` template to format and include `ATR Channel: <lower> - <upper>`.

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
