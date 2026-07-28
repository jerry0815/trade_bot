# Backtest Refresh (T+2 Confirmation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regenerate the README's rolling-backtest performance tables using the strategy configuration bot.py actually runs live (`t2_confirmation=True`), replace the stale numbers, and remove dead/broken exploratory scripts that no longer match `strat_backtest.py`'s API.

**Architecture:** Add one new script, `backtest/generate_readme_tables.py`, that calls the existing `run_experiment_suite()` (already supports `signal_ticker` for cross-signal mode) three times — once per README table — with `SMATrendFollowing(t2_confirmation=True)` in the strategy list. It emits clean markdown table rows to stdout/file so they can be pasted into `README.md`. Delete the 5 stale files identified during project audit (confirmed with user). Update `README.md` and `CHANGELOG.md`. Bring the notebook's strategy definitions in line with `t2_confirmation=True` so it stays a valid reference tool.

**Tech Stack:** Python 3.11, pandas, numpy, yfinance (already in `requirements.txt`). No new dependencies.

## Global Constraints
- Do not change `strat_backtest.py`'s engine behavior — only strategy *instantiation* (adding `t2_confirmation=True`) changes. No new backtest features (per user decision: rotation-aware portfolio math is explicitly out of scope for this pass).
  **Amended 2026-07-27 (mid-execution):** Task 3's implementer discovered `Backtester.run()` silently accepts rolling windows shorter than `period_years` (only rejects completely-empty slices, never checks span length) — inflating window counts (247 vs. expected ~171-180) and violating the README's own "26 years per window" claim. This is a pre-existing correctness bug, not a new feature. User was asked and approved a targeted fix in the engine (see Task 2.5 below) as an explicit, scoped exception to this constraint — everything else in this constraint still holds (no rotation-aware portfolio math, no other engine changes).
- README's stated methodology ("$10,000 lump sum, no DCA, pre-tax") must match what the script actually runs — the notebook's cell 7 currently drifted to `annual_dca=10000`, which contradicts the README text; the new script uses `annual_dca=0` everywhere, matching the README's documented methodology and Tables 2/3.
- Keep the same 5-strategy comparison set (`BuyAndHold`, `SMATrendFollowing` w/ ATR x2.5, `VolatilityFilter`, `EMACrossover`, `RSIMeanReversion`) and the same leverage configs (3x/0.95% exp, 2x/0.95% exp, 1x/0.20% exp) so results are apples-to-apples with the prior README.

---

### Task 1: Delete stale/broken files

**Files:**
- Delete: `run_rolling_comparison.py`
- Delete: `test_defensive_options.py`
- Delete: `test_short_strategy.py`
- Delete: `analyze_covid.py`
- Delete: `bot_history.txt`

**Why:** All four `*.py` scripts import `backtest.strat_backtest.get_defensive_proxy_returns` and/or pass `inverse_leverage=` / `use_defensive_proxy=` to `RollingBacktester(...)` — none of which exist in the current `strat_backtest.py` (verified by reading the file: `RollingBacktester.__init__` only accepts `start_dates, base_ticker, period_years, leverage, expense_ratio, initial_fund, annual_dca, apply_tax, metric_key, metric_label, signal_ticker`). Running any of them raises `AttributeError`/`TypeError` immediately. `bot_history.txt` is an untracked, accidental UTF-16 dump of `git log -p` output (confirmed via `file` + content inspection), not an application log.

**Important:** `git status --porcelain` (checked 2026-07-27) shows all 5 target files as `??` (untracked) — none have ever been committed. Use plain `rm`, not `git rm`, for all five; `git rm` errors on untracked paths.

- [ ] **Step 1: Delete the files**

```bash
rm -f run_rolling_comparison.py test_defensive_options.py test_short_strategy.py analyze_covid.py bot_history.txt
```

- [ ] **Step 2: Verify nothing else imports the deleted files**

Run: `grep -rn "run_rolling_comparison\|test_defensive_options\|test_short_strategy\|analyze_covid" --include=*.py --include=*.yaml --include=*.md .`
Expected: no matches outside this plan file itself.

- [ ] **Step 3: Confirm no git action needed**

Run: `git status --porcelain -- run_rolling_comparison.py test_defensive_options.py test_short_strategy.py analyze_covid.py bot_history.txt`
Expected: empty output — all 5 files were untracked (`??`) before deletion (confirmed 2026-07-27), so removing them leaves no git diff and there is nothing to commit for this task. Do not run `git add`/`git commit` here.

---

### Task 2: Write `backtest/generate_readme_tables.py`

**Files:**
- Create: `backtest/generate_readme_tables.py`

**Interfaces:**
- Consumes: `run_experiment_suite`, `BuyAndHold`, `SMATrendFollowing`, `VolatilityFilter`, `EMACrossover`, `RSIMeanReversion` from `backtest.strat_backtest` (all already exist with the exact signatures read from the file).
- Produces: prints one markdown table per config to stdout, and writes the same content to `backtest/readme_tables_output.md` (gitignored scratch output — not committed, used only to copy numbers into README).

- [ ] **Step 1: Write the script**

```python
"""
Regenerates the three rolling-backtest performance tables shown in README.md.

Run manually after any change to strategy logic (e.g. t2_confirmation) that
should be reflected in the published results:

    python backtest/generate_readme_tables.py

Writes markdown table rows to stdout AND backtest/readme_tables_output.md.
Copy the relevant rows into README.md by hand — this keeps the prose
(commentary, "vs Table 1" analysis) under human editorial control while
guaranteeing the numbers are exactly what the current strategy produces.
"""
import sys
import pandas as pd

sys.path.insert(0, ".")  # allow running as `python backtest/generate_readme_tables.py`
from backtest.strat_backtest import (
    BuyAndHold, SMATrendFollowing, VolatilityFilter, EMACrossover, RSIMeanReversion,
    run_experiment_suite,
)

PERIOD_YEARS = 26
LEVERAGE_CONFIGS = [
    {"name": "3x", "leverage": 3, "expense": 0.0095},
    {"name": "2x", "leverage": 2, "expense": 0.0095},
    {"name": "1x", "leverage": 1, "expense": 0.0020},
]


def build_strategies():
    # Fresh instances per call — strategies carry no mutable run state, but
    # keeping construction local avoids any accidental cross-table sharing.
    return [
        BuyAndHold(),
        SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True),
        EMACrossover(name="EMA 50/200"),
        VolatilityFilter(name="VIX < 25", vix_threshold=25),
        RSIMeanReversion(name="RSI 30/70"),
    ]


def monthly_start_dates(base_ticker):
    end_date = pd.Timestamp.today() - pd.DateOffset(years=PERIOD_YEARS)
    return pd.date_range(start="1980-01-15", end=end_date, freq=pd.DateOffset(months=1))


def summarize(df_res, strategies, metric_label="TWR"):
    rows = []
    for strat in strategies:
        ret_col = f"{strat.name} {metric_label} (%)"
        dd_col = f"{strat.name} Max DD (%)"
        trades_col = f"{strat.name} Total Trades"
        if ret_col not in df_res.columns:
            continue
        worst_idx = df_res[ret_col].idxmin()
        rows.append({
            "Strategy": strat.name,
            "Avg TWR": df_res[ret_col].mean(),
            "Med TWR": df_res[ret_col].median(),
            "Worst TWR": df_res[ret_col].min(),
            "Worst DD": df_res.loc[worst_idx, dd_col],
            "Avg Trades": df_res[trades_col].mean(),
        })
    return rows


def render_markdown_table(title, date_range_note, leverage_to_rows):
    lines = [f"### {title}", f"*{date_range_note}*", "",
             "| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |",
             "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for lev_name, rows in leverage_to_rows.items():
        for r in rows:
            lines.append(
                f"| **{lev_name}** | {r['Strategy']} | {r['Avg TWR']:.2f}% | {r['Med TWR']:.2f}% "
                f"| {r['Worst TWR']:.2f}% | {r['Worst DD']:.2f}% | {r['Avg Trades']:.0f} |"
            )
        lines.append("| | | | | | | |")
    return "\n".join(lines)


def run_table(title, base_ticker, signal_ticker=None):
    strategies = build_strategies()
    start_dates = monthly_start_dates(base_ticker)
    results = run_experiment_suite(
        configs=LEVERAGE_CONFIGS,
        strategies=strategies,
        start_dates=start_dates,
        period_years=PERIOD_YEARS,
        annual_dca=0,
        base_ticker=base_ticker,
        signal_ticker=signal_ticker,
        initial_fund=10000,
        apply_tax=False,
        print_summary=False,
    )
    leverage_to_rows = {}
    n_windows = None
    date_lo = date_hi = None
    for cfg in LEVERAGE_CONFIGS:
        df_res = results[cfg["name"] + " Leverage"] if cfg["name"] + " Leverage" in results else results[cfg["name"]]
        leverage_to_rows[cfg["name"]] = summarize(df_res, strategies)
        if not df_res.empty:
            n_windows = len(df_res)
            date_lo, date_hi = df_res["Start Date"].min(), df_res["Start Date"].max()
    note = f"Date range: {date_lo.date()} to {date_hi.date()} ({n_windows} rolling windows)"
    return render_markdown_table(title, note, leverage_to_rows)


if __name__ == "__main__":
    out = []
    print("Running Table 1: NASDAQ-100 (^NDX)...")
    out.append(run_table("Table 1: NASDAQ-100 (^NDX) — Lump Sum Performance", "^NDX"))

    print("Running Table 2: S&P 500 (^GSPC)...")
    out.append(run_table("Table 2: S&P 500 (^GSPC) — Lump Sum Performance", "^GSPC"))

    print("Running Table 3: NDX returns + GSPC signal...")
    out.append(run_table(
        "Table 3: NASDAQ-100 Returns + S&P 500 Signal — Lump Sum Performance",
        "^NDX", signal_ticker="^GSPC",
    ))

    full_output = "\n\n---\n\n".join(out)
    print("\n" + full_output)
    with open("backtest/readme_tables_output.md", "w", encoding="utf-8") as f:
        f.write(full_output)
    print("\nWritten to backtest/readme_tables_output.md")
```

Note on the `LEVERAGE_CONFIGS` name key: `run_experiment_suite`'s `all_rolling_results` dict is keyed by `config['name']` (read directly from `strat_backtest.py`'s `run_experiment_suite`, `all_rolling_results[config['name']] = df_result`) — i.e. keyed by `"3x"`, `"2x"`, `"1x"` exactly as given in `LEVERAGE_CONFIGS` here, not `"3x Leverage"`. Fix the lookup in `run_table` to `results[cfg["name"]]` only (drop the `+ " Leverage"` fallback branch — it was defensive guesswork; the real key is confirmed from source).

- [ ] **Step 2: Fix the dict-key lookup per the note above**

Replace:
```python
        df_res = results[cfg["name"] + " Leverage"] if cfg["name"] + " Leverage" in results else results[cfg["name"]]
```
with:
```python
        df_res = results[cfg["name"]]
```

- [ ] **Step 3: Smoke-test with a short date range before the full run**

Run a quick manual check that the script's functions work end-to-end on a tiny window count (avoids discovering a bug after a 5-minute full run):

```bash
python -c "
from backtest.generate_readme_tables import build_strategies, run_experiment_suite, LEVERAGE_CONFIGS
import pandas as pd
strategies = build_strategies()
dates = pd.date_range('2015-01-15', '2016-01-15', freq=pd.DateOffset(months=1))
res = run_experiment_suite(configs=LEVERAGE_CONFIGS, strategies=strategies, start_dates=dates, period_years=2, base_ticker='^NDX', initial_fund=10000, print_summary=False)
print({k: len(v) for k, v in res.items()})
"
```
Expected: prints a dict like `{'3x': 13, '2x': 13, '1x': 13}` with no traceback.

- [ ] **Step 4: Add the scratch output file to `.gitignore`**

Edit `.gitignore`, append:
```
backtest/readme_tables_output.md
```

- [ ] **Step 5: Commit**

```bash
git add backtest/generate_readme_tables.py .gitignore
git commit -m "feat: add script to regenerate README backtest tables with current strategy config"
```

---

### Task 2.5: Fix `Backtester.run()` window-length validation

**Files:**
- Modify: `backtest/strat_backtest.py:429-449` (`Backtester.run()`, the slice-and-empty-check block)

**Why:** Confirmed empirically by Task 3's implementer (see
`.superpowers/sdd/2026-07-27-backtest-refresh/task-3-report.md`): for a
nominal `start_date` before a ticker's real data begins (e.g. `^NDX` real
data starts 1985-10-01, `^GSPC` starts 1985-01-02), `Backtester.run()`
slices to `[start_dt, end_dt]` and only checks `if df.empty: return None`
— a window that's actually only ~20.3 years of real data (nominal
start 1980-01-15) is silently accepted as if it were a full 26-year
window. This is user-approved as a scoped bug-fix exception to the "no
engine changes" constraint above.

**Interfaces:**
- Consumes: `self.start_dt`, `self.end_dt` (already set in `__init__` from
  `start_date` and `period_years`), the sliced `df` (a `pd.DataFrame` with
  a `DatetimeIndex`).
- Produces: `Backtester.run()` still returns `None` for a rejected window
  (same contract `RollingBacktester.run()`'s `_run_single` already handles
  via `if res is None: return None`) — no signature or return-shape change
  for windows that DO pass.

- [ ] **Step 1: Add the length check**

In `backtest/strat_backtest.py`, inside `Backtester.run()`, immediately
after the existing:
```python
        # 3. Slice for the test period AFTER signals are generated on full history
        df = df[(df.index >= self.start_dt) & (df.index <= self.end_dt)]
        if df.empty:
            return None
```
add:
```python
        # Reject windows where real data doesn't cover the full requested
        # period (e.g. nominal start_date predates the ticker's actual
        # history). Without this, a window silently truncates instead of
        # being rejected, corrupting rolling-window statistics with
        # shorter, non-comparable periods mixed in as if they were full.
        actual_span_days = (df.index.max() - df.index.min()).days
        requested_span_days = (self.end_dt - self.start_dt).days
        if actual_span_days < requested_span_days * 0.98:
            return None
```

- [ ] **Step 2: Verify existing single-backtest usage still works**

Run:
```bash
python -c "
from backtest.strat_backtest import Backtester, SMATrendFollowing
env = Backtester(base_ticker='^NDX', start_date='2000-01-01', period_years=25, leverage=3, verbose=False)
res = env.run(SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True))
print('result is None:', res is None)
if res: print('strategy_twr:', res['strategy_twr'])
"
```
Expected: `result is None: False` and a printed `strategy_twr` float — this window (2000-2025) is well within both tickers' real data range, so it must still pass. If this prints `None`, the threshold or date-math is wrong — stop and investigate before proceeding, do not loosen the threshold arbitrarily.

- [ ] **Step 3: Verify a known-short window is now correctly rejected**

Run:
```bash
python -c "
from backtest.strat_backtest import Backtester, SMATrendFollowing
env = Backtester(base_ticker='^NDX', start_date='1980-01-15', period_years=26, leverage=3, verbose=False)
res = env.run(SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True))
print('result is None:', res is None)
"
```
Expected: `result is None: True` — this is exactly the degenerate case from the Task 3 report (nominal 1980-01-15 start, real ^NDX data only from 1985-10-01, ~20.3y actual span).

- [ ] **Step 4: Commit**

```bash
git add backtest/strat_backtest.py
git commit -m "fix: reject rolling windows shorter than the requested period instead of silently truncating"
```

---

### Task 3: Run the script and update README.md

**Files:**
- Modify: `README.md:52-133` (Tables 1-3 and their commentary blocks)
- Modify: `README.md:8-24` (strategy description — mention T+2 confirmation, since that's now the live/backtested behavior)

- [ ] **Step 1: Run the full generation**

```bash
python backtest/generate_readme_tables.py
```
This takes several minutes (3 tables × 3 leverage tiers × 5 strategies × ~170-200 rolling windows each, parallelized 8-wide). Expected: no traceback, ends with "Written to backtest/readme_tables_output.md".

- [ ] **Step 2: Read the output and cross-check window counts**

Read `backtest/readme_tables_output.md`. Confirm each table reports window counts and date ranges in the same ballpark as the current README (Table 1: ~171 windows starting ~1986-04; Table 2: ~180 windows starting ~1985-07) — small increases are expected since more calendar time has passed since the README was last generated, not a red flag. A large unexplained drop in window count would indicate a bug (e.g. wrong ticker warmup) — stop and investigate rather than pasting suspicious numbers into README.

- [ ] **Step 3: Replace Table 1, 2, 3 content in README.md**

Using the numbers from `backtest/readme_tables_output.md`, replace the table bodies at `README.md:52-133`, keeping the existing bold-best-result formatting convention and the analytical callout blockquotes below each table (Step 4 covers rewriting those blockquotes' numbers to match).

- [ ] **Step 4: Update the callout commentary under each table**

Recompute the specific numeric claims in the blockquotes under Tables 1-3 (e.g. `README.md:75` "highest average TWR with the lowest drawdown", `README.md:130-133` "SMA 200 produces nearly identical average TWR... ~3 fewer round-trips") against the new numbers — these are prose claims a human should sanity-check against the fresh data, not blindly carry forward.

- [ ] **Step 5: Update the strategy description to mention T+2 confirmation**

In `README.md`'s "Strategy Logic: Dynamic ATR Protection" section (`README.md:8-24`), add a short note that signals require 2 consecutive confirming days before a state change executes (this is what `bot.py:86` actually runs: `SMATrendFollowing(sma_window=200, t2_confirmation=True)`), so the documented rules match both the live bot and the backtest that produced the tables above.

- [ ] **Step 6: Add a CHANGELOG entry**

Add a new top entry to `CHANGELOG.md` (matching the existing entry format/style) describing: README's rolling-backtest tables regenerated with `t2_confirmation=True` to match `bot.py`'s live signal logic; new `backtest/generate_readme_tables.py` script added for future re-generation; 5 stale/broken files removed (name them).

- [ ] **Step 7: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: refresh backtest results tables to reflect T+2 confirmation strategy"
```

---

### Task 4: Align the notebook with the live strategy config

**Files:**
- Modify: `backtest/TQQQ_Trend_Strategy_Simulator.ipynb` (cells 3, 7, 9, 13 — every `SMATrendFollowing(...)` construction)

**Why:** The notebook is kept as an interactive reference/exploration tool (per its own header markdown). Leaving its example strategy instantiations without `t2_confirmation=True` means anyone re-running it gets numbers that no longer match either `bot.py` or the refreshed README — a silent trap for future you.

- [ ] **Step 1: Update strategy constructions**

In each notebook code cell that builds `SMATrendFollowing(sma_window=200, atr_multiplier=2.5)` (cells 3, 7, 9, 13 per the notebook dump), add `t2_confirmation=True`.

- [ ] **Step 2: Fix cell 7's DCA drift**

Cell 7 currently passes `annual_dca=10000` under a "Rolling Backtest Suite (NDX — DCA)" heading, while the README text above it (and Tables 2/3) describe lump-sum, no-DCA methodology. Leave cell 7's DCA example as an intentional *separate* DCA demonstration (it's clearly labeled as such), but add a new markdown note directly above it clarifying: "This cell demonstrates DCA mode; README Table 1 uses `annual_dca=0` (see `backtest/generate_readme_tables.py`)." This prevents the notebook from being mistaken for the README's data source again.

- [ ] **Step 3: Save and commit**

```bash
git add backtest/TQQQ_Trend_Strategy_Simulator.ipynb
git commit -m "docs: sync notebook strategy examples with t2_confirmation=True"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = delete stale files (user-approved). Task 2 = new backtest generation script covering "update backtest to test with recent changes." Task 3 = README update with fresh results (item 2 of the user's request). Task 4 = keeps the notebook (an existing project artifact) consistent so it doesn't silently drift again.
- **No placeholders:** every step has runnable code or an exact file:line target pulled from the actual source read during planning.
- **Type/name consistency:** `run_experiment_suite`, `RollingBacktester`, `Backtester`, `SMATrendFollowing(sma_window, buffer_pct, atr_multiplier, t2_confirmation)` signatures all copied verbatim from `backtest/strat_backtest.py` as read on 2026-07-27; `LEVERAGE_CONFIGS` dict key (`config['name']`) confirmed against `run_experiment_suite`'s actual `all_rolling_results[config['name']]` line.
