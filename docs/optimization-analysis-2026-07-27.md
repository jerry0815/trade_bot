# Codebase Optimization & Refactor Analysis — 2026-07-27

Scope: full repo as of commit `ee35074` (post backtest-refresh work). This is
a point-in-time audit, not an implementation — nothing here has been
changed. File:line references are accurate as of this commit.

## Summary

The core engine (`backtest/strat_backtest.py`) is solid: vectorized,
reasonably documented, and already survived several real production bugs
(rate limits, SQLite locking, NaN propagation — see `CHANGELOG.md`). The
biggest risks are outside the engine: **zero automated tests** for math
that handles real money, **duplicated logic** in ad-hoc scripts, and
**tight coupling** between the SMA/ATR strategy and the reporting/engine
code that will make item 4 (generalizing for other strategies) harder than
it needs to be.

Ordered roughly by impact.

---

## 1. No automated test suite (highest priority)

`pytest` is installed (`.pytest_cache/` exists) but there are no real
tests — the files that matched `test_*.py` before this session's cleanup
(`test_short_strategy.py`, `test_defensive_options.py`) were ad-hoc
scripts with `if __name__ == "__main__":` blocks, not pytest tests, and
they were broken (called removed APIs).

`Backtester._run_portfolio_math` (`backtest/strat_backtest.py:484-613`) is
~130 lines of scalar-loop accounting: entry/exit day return blending,
leverage drag, tax lots, drawdown tracking. It has already had multiple
silent bugs fixed via ad-hoc discovery (see `CHANGELOG.md`'s 2026-07-11
entry: "`f.result()` called twice", "wrong SMA when `sma_window != 200`",
"inflated trade counts"). None of those regressions would be caught today
if reintroduced — there's no regression suite.

**Recommendation:** Add `tests/test_strat_backtest.py` with unit tests for:
- `SMATrendFollowing._add_indicator_logic` — a small synthetic price series
  with known SMA/ATR crossings, asserting `in_market` flips on the right
  day (and, separately, that T+2 confirmation delays the flip by exactly
  one day when configured).
- `_run_portfolio_math` — a synthetic 5-10 row DataFrame with known
  returns, asserting `final_value`, `max_drawdown`, and one tax scenario
  by hand-calculated expected values. This is the highest-value test to
  write given its bug history.
- `_calculate_trade_stats` — trade counting on a known `in_market` series.

No network access needed for any of these — synthetic DataFrames, not
`yf.download`.

---

## 2. Duplicated defensive-rotation logic (correctness risk)

`show_recent_signals.py:15-46` hand-recomputes True Range, ATR, and 126-day
momentum instead of calling the existing `get_current_defensive_rotation()`
(`backtest/strat_backtest.py:118-150`) and `prep_base_indicators()`
(`backtest/strat_backtest.py:62-103`) that `bot.py` actually uses in
production.

Worse, the two implementations have already **drifted**: the live rotation
picker (`get_current_defensive_rotation`) considers exactly `["KMLM", "TLT",
"GLD", "SHY"]`, while `show_recent_signals.py:19` considers `["KMLM",
"RYMTX", "TLT", "VUSTX", "GLD", "SHY"]` with manual fallback-ticker logic
(`RYMTX`→`KMLM`, `VUSTX`→`TLT`) that doesn't exist anywhere in the
production path. Running this script today would report a "what would the
bot have held" history that can disagree with what `bot.py` actually
reports live, for no reason a reader would discover without reading both
files side by side.

**Recommendation:** Either delete `show_recent_signals.py` (its job is a
strict subset of what a future rolling-backtest report could show) or
rewrite it to import and call `get_current_defensive_rotation()` +
`prep_base_indicators()` directly, deleting its private
reimplementation.

---

## 3. Reusability: the engine is coupled to one strategy's shape

This is the load-bearing finding for item 4 (generalizing the project for
other strategies) — flagged here with concrete file:line evidence so the
separate implementation plan (item 4) can point back at it.

- `Backtester._print_results` (`backtest/strat_backtest.py:616-659`) mixes
  computation with `print()`-based presentation — there's no way to get a
  `RollingBacktester` result without either the console output or manually
  reaching into `df.columns` built from `f"{strat.name} ..."` string
  interpolation (`backtest/strat_backtest.py:715-717`). Any new strategy or
  reporting surface (e.g. a future web dashboard, or `bot.py` itself) has
  to either parse those column names or duplicate the string formatting.
- `bot.py:11-81` (`generate_market_report`) hardcodes ticker roles
  (`monitor_ticker`, `leveraged_ticker`, `sp500_ticker`) and the specific
  ATR-bound/T+2 report fields (`upper_bound`, `lower_bound`,
  `days_in_current_state`) that only `SMATrendFollowing.get_live_stats`
  populates (`backtest/strat_backtest.py:261-295`). A different strategy
  (e.g. `EMACrossover`) would need its own bespoke report function, not a
  drop-in swap — `BaseStrategy.get_live_stats` (`backtest/strat_backtest.py:183-238`)
  only returns the common fields, and `format_signal_section` in `bot.py`
  reads strategy-specific keys (`upper_bound`, `trend`) with `.get(...,
  default)` fallbacks rather than a real interface contract.
- `get_current_defensive_rotation` (`backtest/strat_backtest.py:118-150`)
  hardcodes both the asset universe (`KMLM/TLT/GLD/SHY`) and the momentum
  window (126 days) as literals inside the function body, not parameters —
  reasonable for a single-strategy bot, a hard stop for a general
  "defensive rotation" building block reusable by other strategies.

None of this needs fixing for items 1-3 of the current request. It's the
concrete evidence base for item 4's plan.

---

## 4. Latent naming/behavior smells

- `backtest/strat_backtest.py:233`: `"qqq_price": float(self.df['Close'].iloc[-1].item())`
  — the dict key is literally `qqq_price` even when `get_live_stats` is
  called for the S&P 500 (`bot.py:24`, `strategy.get_live_stats(sp500_ticker,
  sp500_ticker, ...)`), so `stats_sp500['qqq_price']` actually holds the
  SPY price. `bot.py:49` reads it as `stats['qqq_price']` inside a function
  parameterized by `ticker` — works today only because the key is always
  present regardless of which ticker was requested, but the name actively
  misleads. (`leveraged_price` was already renamed away from `tqqq_price`
  for exactly this reason per `CHANGELOG.md`'s 2026-07-14 entry — this is
  the same class of leftover.) Rename to `price` or `monitor_price`.
- `.item()` on `backtest/strat_backtest.py:233` is redundant —
  `self.df['Close'].iloc[-1]` is already a numpy scalar, and the line right
  below it (`leveraged_df['Close'].iloc[-1]`, line 234) wraps the same
  pattern in `float(...)` without `.item()`. Harmless but inconsistent;
  drop the `.item()` call for consistency.
- `RollingBacktester.run()` hardcodes `workers = min(8, len(self.start_dates))`
  (`backtest/strat_backtest.py:720`) rather than deriving from
  `os.cpu_count()`. Not wrong, just a magic number that under-uses bigger
  machines and over-subscribes small ones.

---

## 5. Dependency/process hygiene

- `requirements.txt` pins nothing (`yfinance`, `pandas`, `requests` with no
  version bounds). Given `CHANGELOG.md` shows *three* separate yfinance API
  breakages already fixed reactively (2026-07-14 `IndexError`, 2026-07-22
  `OperationalError`/rate limits), an unpinned `yfinance` is exactly the
  dependency most likely to break the daily GitHub Actions run again
  without warning. At minimum pin a floor (`yfinance>=0.2.40`) so a known-
  working version range is documented; consider `pip freeze`-style exact
  pins with a periodic manual bump.
- `.github/workflows/daily_check.yaml:12` grants `permissions: contents:
  write`, left over from before commit `19eea86` ("transition to stateless
  architecture and remove github actions git-push dependency"). The
  current `bot.py` performs no file writes or git operations — it only
  reads env vars and POSTs to a Discord webhook. `contents: write` is now
  unnecessary broad permission for the workflow's `GITHUB_TOKEN`; narrow it
  to `contents: read` (or drop the block entirely, which defaults to read).
- `docs/superpowers/plans/task-1-brief.md` through `task-3-review-package.md`
  (8 files, dated 2026-07-23) are leftover subagent-driven-development
  scratch artifacts from a prior session, currently untracked
  (`git status` shows all of `docs/` as `??`). They predate this session's
  convention of keeping that scratch workspace under the gitignored
  `.superpowers/` directory. Recommend either deleting them (if that prior
  work is done and merged) or moving them under `.superpowers/` so they
  stop appearing as uncommitted changes in `git status` indefinitely.

---

## 6. Minor / stylistic

- `backtest/strat_backtest.py:24-50`: `_download_with_retry` catches bare
  `Exception` around `yf.download` and retries with exponential backoff up
  to 5 times (15s→30s→60s→120s→240s, ~7.5 minutes worst case). This is
  appropriate for transient network/rate-limit errors, but it also retries
  on any *programming* error (e.g. a typo'd ticker string raising inside
  yfinance) for the full 7.5 minutes before surfacing the real problem.
  Consider narrowing the caught exception type if yfinance exposes a
  specific rate-limit/network exception class, or logging the exception
  type on each attempt so a programming error is at least visible sooner
  in the retry logs (it already prints the exception — this is a minor
  ergonomics improvement, not a correctness issue).
- `bot_history.txt`-style accidental dumps (already removed this session)
  suggest it's worth double-checking shell history for other `> file.txt`
  redirects that might have landed in the repo root before a future
  `git add -A`. Nothing else found in this pass.

---

## Non-findings (looked, no issue)

- Thread-safety of `DATA_CACHE`/`SIGNAL_CACHE`: relies on "pre-warm before
  launching threads" discipline rather than locking, but every current call
  site (`RollingBacktester.run()`, `run_experiment_suite`) does pre-warm
  correctly before spawning workers. Fragile if a future caller skips the
  pre-warm step, but not a live bug today.
- Tax lot accounting (`backtest/strat_backtest.py:552-585`) — single-lot
  FIFO is correct for this engine's one-position-at-a-time model; no
  partial-fill or multi-lot scenario exists to get wrong.

---

## 7. Addendum (2026-07-28): Overlapping-window statistical bias — future work

Flagged during review of Table 4's 44-variant sweep, not part of the
original 2026-07-27 audit above. Applies to every rolling-window table in
this project (Tables 1-4): `warmup_aware_start_dates()` steps candidate
start dates **monthly** over a **26-year** window, so adjacent windows
share all but one month of history. The ~172-193 "windows" reported per
table are not independent samples — the same handful of real market
events (the dot-com crash, 2008 GFC, COVID crash, 2022 bear market) each
appear in dozens of overlapping windows and get counted that many times
in the Avg/Med TWR statistics. This can make average/median figures look
more statistically solid than they are, and risks over-weighting whichever
regime happens to fall in more of the sampled windows purely due to the
monthly step cadence, not genuine strategy edge.

**Two candidate fixes, not yet designed or implemented:**
1. **Regime-segmented reporting** — report results broken out by named
   historical regime (dot-com, GFC, COVID, 2022, etc.) alongside the
   pooled rolling-window average, so a reader can see how many genuinely
   independent regimes the strategy has actually been tested against.
   Simpler to implement; the tradeoff is fewer independent data points to
   compare (a handful of regimes vs. "172 windows"), which is a more
   honest picture but a less statistically powerful one on its face.
2. **Block bootstrap resampling** — resample the underlying daily return
   series in autocorrelation-preserving blocks to construct a proper
   confidence interval that accounts for the true (much smaller) effective
   sample size, rather than treating each rolling window as an independent
   observation. More statistically rigorous; more implementation work
   (would need a documented block-length choice and doesn't map as
   intuitively onto "which historical event mattered").

No decision made yet on which to pursue — recorded here so it isn't lost.

A related but distinct question — whether Table 4's parameter selection
itself overfits — is addressed separately in
`docs/out-of-sample-validation-2026-07-28.md`.
