# 3x TQQQ Signal & Parameter Comparison (Table 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new README Table 4 comparing SMA and EMA across ATR multiplier, signal source, and T+2 confirmation at 3x leverage on `^NDX` (TQQQ), and mechanically determine a "best real-world practice" pick from the results.

**Architecture:** Extend `EMACrossover` with two new opt-in parameters (`atr_multiplier`, `t2_confirmation`) that default to today's exact behavior when unset. Promote two helper functions already written for `generate_readme_tables.py` (warmup-aware start dates, independent-Worst-DD summarization) into `strat_backtest.py` so a new script, `backtest/generate_signal_comparison.py`, can reuse them without duplicating logic. Run the new script (44 variants, one 3x-leverage rolling-26-year backtest each) and hand-transcribe the output into a new README Table 4.

**Tech Stack:** Python 3.11, pandas, numpy — same as the rest of the project. No new dependencies.

**Full design context:** `docs/superpowers/specs/2026-07-28-signal-comparison-design.md` (read for rationale; this plan is the executable version).

## Global Constraints

- **No regression to existing behavior.** `EMACrossover()` called with no `atr_multiplier`/`t2_confirmation` args (i.e. every existing call site — Tables 1-3, the notebook) must produce byte-identical `in_market` output and `Backtester.run()` results to before this change. Verified explicitly in Task 1 via before/after diff, not assumed.
- **Mechanical extraction only.** Task 2's helper-function move must not change either function's logic — copy the body verbatim, only the location and (for `monthly_start_dates` → `warmup_aware_start_dates`) the name and an explicit `period_years` parameter (it currently closes over a module-level `PERIOD_YEARS` constant that won't exist in `strat_backtest.py`).
- **Best-practice pick is mechanical, not editorial.** Compute it in the script per the design's rule (exclude worst quartile by Worst DD across all 44 variants, then max Avg TWR among the rest) — do not let README commentary override or second-guess the computed pick without saying so explicitly if you do.
- **Leverage fixed at 3x only** for every variant in this table — do not add 2x/1x tiers, that's out of scope (Tables 1-3 already cover those).

---

### Task 1: Extend `EMACrossover` with ATR buffer and T+2 confirmation, verified non-regressing

**Files:**
- Modify: `backtest/strat_backtest.py:361-376` (the `EMACrossover` class)

**Interfaces:**
- Produces: `EMACrossover(name="EMA 50/200 Cross", fast_period=50, slow_period=200, t2_confirmation=False, atr_multiplier=None)` — two new constructor kwargs, both optional, both default to today's behavior.

- [ ] **Step 1: Capture a baseline BEFORE changing any code**

Run this from the repo root and save the exact output somewhere you can compare against later (a scratch file, or just keep it in your terminal scrollback):

```bash
python -c "
from backtest.strat_backtest import EMACrossover, Backtester
env = Backtester(base_ticker='^NDX', start_date='2005-01-01', period_years=15, leverage=3, verbose=False)
strat = EMACrossover()
res = env.run(strat)
print('name:', strat.name)
print('twr:', res['strategy_twr'])
print('dd:', res['max_drawdown'])
print('trades:', res['total_trades'])
print('final_value:', res['final_value'])
"
```

- [ ] **Step 2: Replace the `EMACrossover` class**

Replace `backtest/strat_backtest.py:361-376`:

```python
class EMACrossover(BaseStrategy):
    def __init__(self, name="EMA 50/200 Cross", fast_period=50, slow_period=200):
        super().__init__(name)
        self.fast = fast_period
        self.slow = slow_period

    def _add_indicator_logic(self, df):
        df = df.copy()

        fast_ema = df['Close'].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df['Close'].ewm(span=self.slow, adjust=False).mean()

        raw_signal = fast_ema > slow_ema
        shifted = raw_signal.shift(1)
        df['in_market'] = np.where(shifted.isna(), False, shifted).astype(bool)
        return df
```

with:

```python
class EMACrossover(BaseStrategy):
    def __init__(self, name="EMA 50/200 Cross", fast_period=50, slow_period=200,
                 t2_confirmation=False, atr_multiplier=None):
        if atr_multiplier:
            name += f" (ATR x{atr_multiplier})"
        if t2_confirmation:
            name += " [T+2]"
        super().__init__(name)
        self.fast = fast_period
        self.slow = slow_period
        self.t2_confirmation = t2_confirmation
        self.atr_multiplier = atr_multiplier

    def _add_indicator_logic(self, df):
        df = df.copy()

        fast_ema = df['Close'].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df['Close'].ewm(span=self.slow, adjust=False).mean()

        if self.atr_multiplier or self.t2_confirmation:
            # Enhanced path: ATR dead-zone and/or T+2 confirmation requested.
            # Treat "fast above slow (by more than the ATR band, if set)"
            # and "fast below slow (by more than the band)" as independent
            # buy/sell events, each optionally 2-day-confirmed, then
            # forward-fill state — mirrors SMATrendFollowing's pattern and
            # gives symmetric confirmation on both entry and exit (a naive
            # rolling-min on the raw crossover boolean would confirm entry
            # over 2 days but exit after just 1).
            if self.atr_multiplier:
                spread = fast_ema - slow_ema
                buy_signal = spread > (df['ATR'] * self.atr_multiplier)
                sell_signal = spread < -(df['ATR'] * self.atr_multiplier)
            else:
                buy_signal = fast_ema > slow_ema
                sell_signal = fast_ema <= slow_ema

            if self.t2_confirmation:
                buy_signal = buy_signal.rolling(window=2).min() == 1
                sell_signal = sell_signal.rolling(window=2).min() == 1

            state = pd.Series(np.nan, index=df.index)
            state.loc[buy_signal] = 1.0
            state.loc[sell_signal] = 0.0
            initial_state_val = 1.0 if fast_ema.iloc[0] > slow_ema.iloc[0] else 0.0
            raw_signal = state.ffill().fillna(initial_state_val)
            df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)
        else:
            # Original path — byte-identical to pre-change behavior when
            # neither knob is set. Do not merge this with the branch above;
            # this exact duplication is what guarantees Tables 1-3's
            # already-published EMA numbers cannot shift.
            raw_signal = fast_ema > slow_ema
            shifted = raw_signal.shift(1)
            df['in_market'] = np.where(shifted.isna(), False, shifted).astype(bool)
        return df
```

- [ ] **Step 3: Re-run the exact same baseline command and diff**

```bash
python -c "
from backtest.strat_backtest import EMACrossover, Backtester
env = Backtester(base_ticker='^NDX', start_date='2005-01-01', period_years=15, leverage=3, verbose=False)
strat = EMACrossover()
res = env.run(strat)
print('name:', strat.name)
print('twr:', res['strategy_twr'])
print('dd:', res['max_drawdown'])
print('trades:', res['total_trades'])
print('final_value:', res['final_value'])
"
```

Expected: every printed value is **identical** to Step 1's output (same `name` — `EMA 50/200 Cross`, no suffix, since both new kwargs default off — and identical `twr`/`dd`/`trades`/`final_value` to the last decimal place). If anything differs, the "byte-identical when both knobs are off" invariant is broken — stop and find the discrepancy before proceeding; do not adjust the "original path" branch to force a match.

- [ ] **Step 4: Sanity-check the new knobs actually change behavior when enabled**

```bash
python -c "
from backtest.strat_backtest import EMACrossover, Backtester
env = Backtester(base_ticker='^NDX', start_date='2005-01-01', period_years=15, leverage=3, verbose=False)
plain = env.run(EMACrossover())
atr_only = env.run(EMACrossover(atr_multiplier=2.5))
t2_only = env.run(EMACrossover(t2_confirmation=True))
both = env.run(EMACrossover(atr_multiplier=2.5, t2_confirmation=True))
for label, res in [('plain', plain), ('atr_only', atr_only), ('t2_only', t2_only), ('both', both)]:
    print(label, res['strategy_twr'], res['total_trades'])
"
```
Expected: no traceback; `atr_only`/`t2_only`/`both` each produce a *different* `total_trades` count than `plain` (confirming each knob actually changes the signal, not a no-op) — the exact numbers don't matter here, only that they're not all identical to `plain`.

- [ ] **Step 5: Commit**

```bash
git add backtest/strat_backtest.py
git commit -m "feat: add ATR buffer and T+2 confirmation options to EMACrossover"
```

---

### Task 2: Extract shared helpers into `strat_backtest.py`

**Files:**
- Modify: `backtest/strat_backtest.py` (append two new functions at end of file, after line 818)
- Modify: `backtest/generate_readme_tables.py:14-24` (imports), `:54-90` (remove local `monthly_start_dates`/`summarize`), `:114` and `:132` (call sites)

**Interfaces:**
- Produces: `warmup_aware_start_dates(tickers, period_years)` — same body as today's `generate_readme_tables.py:54-67` `monthly_start_dates`, but takes `period_years` as an explicit parameter instead of closing over a module-level constant.
- Produces: `summarize_rolling_results(df_res, strategies, metric_label="TWR")` — identical body to today's `generate_readme_tables.py:70-90` `summarize`, just renamed and relocated.

- [ ] **Step 1: Append the two functions to `strat_backtest.py`**

Add at the end of `backtest/strat_backtest.py` (after the existing `return all_rolling_results` that closes `run_experiment_suite`, currently the file's last line):

```python

def warmup_aware_start_dates(tickers, period_years):
    """Generate monthly rolling-window start dates, warmup-aware per ticker.

    The earliest usable start date is the latest of the given tickers'
    real data start dates, plus a 210-calendar-day offset (~200 trading
    days) so the 200-day SMA/EMA indicators are fully warmed up before
    the window begins. `tickers` should include every ticker actually
    used by the backtest (both base and signal ticker for cross-signal
    setups) since the window can't start until *all* of them have data.
    """
    warmup_start = max(get_cached_data(t).index[0] for t in tickers) + pd.DateOffset(days=210)
    end_date = pd.Timestamp.today() - pd.DateOffset(years=period_years)
    return pd.date_range(start=warmup_start, end=end_date, freq=pd.DateOffset(months=1))


def summarize_rolling_results(df_res, strategies, metric_label="TWR"):
    """Summarizes a RollingBacktester result DataFrame into per-strategy stats."""
    rows = []
    for strat in strategies:
        ret_col = f"{strat.name} {metric_label} (%)"
        dd_col = f"{strat.name} Max DD (%)"
        trades_col = f"{strat.name} Total Trades"
        if ret_col not in df_res.columns:
            continue
        rows.append({
            "Strategy": strat.name,
            "Avg TWR": df_res[ret_col].mean(),
            "Med TWR": df_res[ret_col].median(),
            "Worst TWR": df_res[ret_col].min(),
            # Worst DD must be the deepest drawdown observed across ALL windows
            # for this strategy — independent of which window had the worst
            # TWR. Matches this same file's print-summary convention above.
            "Worst DD": df_res[dd_col].min(),
            "Avg Trades": df_res[trades_col].mean(),
        })
    return rows
```

- [ ] **Step 2: Update `generate_readme_tables.py` to use the shared functions**

In `backtest/generate_readme_tables.py`:

1. Change the import block (`:21-24`) from:
```python
from backtest.strat_backtest import (
    BuyAndHold, SMATrendFollowing, VolatilityFilter, EMACrossover, RSIMeanReversion,
    get_cached_data, run_experiment_suite,
)
```
to:
```python
from backtest.strat_backtest import (
    BuyAndHold, SMATrendFollowing, VolatilityFilter, EMACrossover, RSIMeanReversion,
    run_experiment_suite, warmup_aware_start_dates, summarize_rolling_results,
)
```
(`get_cached_data` is no longer called directly in this file once `monthly_start_dates` moves out — drop it from the import. If anything else in the file still uses it, keep it; check before removing.)

2. Delete the local `monthly_start_dates` function (`:54-67`) and the local `summarize` function (`:70-90`) entirely.

3. In `run_table()` (`:107-145`), change the call site at `:114` from:
```python
    start_dates = monthly_start_dates(tickers)
```
to:
```python
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
```

4. Change the call site at `:132` from:
```python
        leverage_to_rows[cfg["name"]] = summarize(df_res, strategies)
```
to:
```python
        leverage_to_rows[cfg["name"]] = summarize_rolling_results(df_res, strategies)
```

- [ ] **Step 3: Verify the extraction didn't change behavior**

```bash
python -c "
from backtest.strat_backtest import warmup_aware_start_dates, summarize_rolling_results
dates = warmup_aware_start_dates(['^NDX'], 26)
print('NDX 26y:', dates[0].date(), 'to', dates[-1].date(), f'({len(dates)} windows)')
dates2 = warmup_aware_start_dates(['^GSPC'], 26)
print('GSPC 26y:', dates2[0].date(), 'to', dates2[-1].date(), f'({len(dates2)} windows)')
"
```
Expected: NDX's first date is `1986-04-29` (matches `^NDX`'s real data start `1985-10-01` + 210 days), GSPC's first date is `1985-07-31` (matches `^GSPC`'s `1985-01-02` + 210 days) — same values already published in README's Table 1/2. If either differs, the extraction introduced a bug — stop and investigate.

Then confirm the module still imports and runs cleanly:
```bash
python -c "import backtest.generate_readme_tables as m; print('imports OK:', m.PERIOD_YEARS, m.build_strategies()[0].name)"
```
Expected: no traceback, prints `imports OK: 26 Buy & Hold`.

Do **not** run the full `generate_readme_tables.py` end-to-end in this task (it takes several minutes and Task 4 of the *previous* plan already regenerated and committed Tables 1-3 — there's no need to re-verify the full numeric output again here, only that the refactor didn't break the two extracted functions' logic, which Step 3 already confirms).

- [ ] **Step 4: Commit**

```bash
git add backtest/strat_backtest.py backtest/generate_readme_tables.py
git commit -m "refactor: promote warmup-aware start dates and result summarization into strat_backtest.py"
```

---

### Task 3: Write `backtest/generate_signal_comparison.py`

**Files:**
- Create: `backtest/generate_signal_comparison.py`

**Interfaces:**
- Consumes: `SMATrendFollowing`, `EMACrossover`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` from `backtest.strat_backtest` (all confirmed to exist with these exact signatures after Tasks 1-2).
- Produces: prints the computed "best practice" pick plus two markdown tables to stdout, and writes the same content to `backtest/signal_comparison_output.md`.

- [ ] **Step 1: Write the script**

```python
"""
Generates README's Table 4: a 3x-leverage ^NDX (TQQQ) comparison of SMA
and EMA across ATR multiplier, signal source, and T+2 confirmation.

Run manually:
    python backtest/generate_signal_comparison.py

Writes the computed "best real-world practice" pick plus two markdown
tables (SMA sweep, EMA sweep) to stdout AND
backtest/signal_comparison_output.md. Copy the relevant content into
README.md by hand — same generate-then-hand-transcribe pattern as
generate_readme_tables.py.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, EMACrossover, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "signal_comparison_output.md"

PERIOD_YEARS = 26
LEVERAGE_CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR_VALUES = [1.5, 2.0, 2.5, 3.0, 3.5]
SIGNAL_SOURCES = [("Own (^NDX)", None), ("S&P 500 (^GSPC)", "^GSPC")]
T2_STATES = [("Off", False), ("On", True)]


def build_sma_variants():
    variants = []
    for atr in ATR_VALUES:
        for signal_label, signal_ticker in SIGNAL_SOURCES:
            for t2_label, t2 in T2_STATES:
                strat = SMATrendFollowing(sma_window=200, atr_multiplier=atr, t2_confirmation=t2)
                variants.append({
                    "strategy": strat,
                    "signal_ticker": signal_ticker,
                    "row": {"ATR": f"x{atr}", "Signal": signal_label, "T+2": t2_label},
                })
    return variants


def build_ema_variants():
    variants = []
    for atr in [None] + ATR_VALUES:
        for signal_label, signal_ticker in SIGNAL_SOURCES:
            for t2_label, t2 in T2_STATES:
                strat = EMACrossover(atr_multiplier=atr, t2_confirmation=t2)
                variants.append({
                    "strategy": strat,
                    "signal_ticker": signal_ticker,
                    "row": {"ATR": f"x{atr}" if atr else "None", "Signal": signal_label, "T+2": t2_label},
                })
    return variants


def run_variant(variant):
    strat = variant["strategy"]
    signal_ticker = variant["signal_ticker"]
    tickers = ["^NDX"] if signal_ticker is None else ["^NDX", signal_ticker]
    start_dates = warmup_aware_start_dates(tickers, PERIOD_YEARS)
    results = run_experiment_suite(
        configs=[LEVERAGE_CONFIG],
        strategies=[strat],
        start_dates=start_dates,
        period_years=PERIOD_YEARS,
        annual_dca=0,
        base_ticker="^NDX",
        signal_ticker=signal_ticker,
        initial_fund=10000,
        apply_tax=False,
        print_summary=False,
    )
    df_res = results[LEVERAGE_CONFIG["name"]]
    summary = summarize_rolling_results(df_res, [strat], metric_label="TWR")
    if not summary:
        return None
    row = dict(variant["row"])
    row.update(summary[0])
    row["n_windows"] = len(df_res)
    return row


def render_table(title, rows):
    rows_sorted = sorted(rows, key=lambda r: r["Avg TWR"], reverse=True)
    lines = [f"### {title}", "",
             "| ATR | Signal | T+2 | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |",
             "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows_sorted:
        lines.append(
            f"| {r['ATR']} | {r['Signal']} | {r['T+2']} | {r['Avg TWR']:.2f}% | {r['Med TWR']:.2f}% "
            f"| {r['Worst TWR']:.2f}% | {r['Worst DD']:.2f}% | {r['Avg Trades']:.0f} |"
        )
    return "\n".join(lines)


def pick_best_practice(all_rows):
    n = len(all_rows)
    excluded_count = n // 4  # worst quartile by Worst DD (deepest/most negative)
    ranked_by_dd = sorted(all_rows, key=lambda r: r["Worst DD"])  # most negative (worst) first
    excluded_ids = {id(r) for r in ranked_by_dd[:excluded_count]}
    candidates = [r for r in all_rows if id(r) not in excluded_ids]
    best = max(candidates, key=lambda r: r["Avg TWR"])
    return best, excluded_count


if __name__ == "__main__":
    sma_variants = build_sma_variants()
    print(f"Running SMA sweep ({len(sma_variants)} variants)...")
    sma_rows = []
    for i, variant in enumerate(sma_variants, 1):
        row = run_variant(variant)
        print(f"  [{i}/{len(sma_variants)}] {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = "SMA"
            sma_rows.append(row)

    ema_variants = build_ema_variants()
    print(f"Running EMA sweep ({len(ema_variants)} variants)...")
    ema_rows = []
    for i, variant in enumerate(ema_variants, 1):
        row = run_variant(variant)
        print(f"  [{i}/{len(ema_variants)}] {variant['row']} -> {'ok' if row else 'NO DATA'}")
        if row:
            row["Strategy"] = "EMA"
            ema_rows.append(row)

    sma_table = render_table("SMA — ATR & Signal Sweep (3x Leverage)", sma_rows)
    ema_table = render_table("EMA — ATR & Signal Sweep (3x Leverage)", ema_rows)

    all_rows = sma_rows + ema_rows
    best, excluded_count = pick_best_practice(all_rows)
    best_line = (
        f"BEST PRACTICE: {best['Strategy']} | ATR={best['ATR']} | Signal={best['Signal']} | T+2={best['T+2']}\n"
        f"  Avg TWR: {best['Avg TWR']:.2f}% | Worst DD: {best['Worst DD']:.2f}% | Avg Trades: {best['Avg Trades']:.0f}\n"
        f"  (highest Avg TWR among the {len(all_rows) - excluded_count} variants remaining after "
        f"excluding the {excluded_count} deepest-drawdown outliers out of {len(all_rows)} total)"
    )

    full_output = best_line + "\n\n---\n\n" + sma_table + "\n\n---\n\n" + ema_table
    print("\n" + full_output)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"\nWritten to {OUTPUT_PATH}")
```

- [ ] **Step 2: Smoke-test with a reduced combination set before the full 44-variant run**

```bash
python -c "
from backtest.generate_signal_comparison import build_sma_variants, build_ema_variants, run_variant
sma = build_sma_variants()
ema = build_ema_variants()
print('SMA variants:', len(sma), '| EMA variants:', len(ema))
r1 = run_variant(sma[0])
print('sample SMA row:', r1)
r2 = run_variant(ema[0])
print('sample EMA row (ATR=None baseline):', r2)
r3 = run_variant(ema[6])
print('sample EMA row (with ATR):', r3)
"
```
Expected: `SMA variants: 20 | EMA variants: 24`, and all three sample rows print a dict with real numeric `Avg TWR`/`Worst DD`/etc. values, no traceback. This confirms the wiring works before committing to the full ~10-minute run.

- [ ] **Step 3: Add the scratch output file to `.gitignore`**

Append to `.gitignore`:
```
backtest/signal_comparison_output.md
```

- [ ] **Step 4: Commit**

```bash
git add backtest/generate_signal_comparison.py .gitignore
git commit -m "feat: add script to generate 3x TQQQ signal & parameter comparison"
```

---

### Task 4: Run the full sweep and publish README Table 4

**Files:**
- Modify: `README.md` (add a new "Table 4" section after Table 3's closing blockquote, before the "Changelog" section)
- Modify: `CHANGELOG.md` (new entry)

- [ ] **Step 1: Run the full sweep**

```bash
python backtest/generate_signal_comparison.py
```
This runs 44 separate rolling-26-year backtests at 3x leverage (each internally parallelized 8-wide) — expect several minutes, comparable to the existing `generate_readme_tables.py` run. Expect no tracebacks and a final "Written to backtest/signal_comparison_output.md" line.

- [ ] **Step 2: Sanity-check the output before transcribing**

Read `backtest/signal_comparison_output.md`. Confirm:
- 20 rows in the SMA table, 24 rows in the EMA table (matches the variant counts from Task 3).
- The `BEST PRACTICE` line names one specific, real combination (not a placeholder) with real numbers.
- Every row has plausible values (Avg TWR roughly in the same ballpark as Table 1's SMA/EMA rows at 3x, since this is the same `^NDX`/26-year/3x setup, just with parameter variations — a wildly different order of magnitude would indicate a bug, not a genuine finding).

If anything looks structurally wrong (missing rows, all-identical numbers across different ATR values suggesting the parameter isn't actually being applied, etc.), investigate before transcribing — don't publish suspect numbers.

- [ ] **Step 3: Add README Table 4**

Insert a new section into `README.md` immediately after Table 3's closing blockquote (the "vs. Table 1 (NDX own signal) and Table 2..." paragraph) and before the "### **Changelog**" section. Structure:

```markdown
---

### Table 4: 3x TQQQ — Signal & Parameter Comparison (SMA vs EMA)
*^NDX base, 3x leverage only. Sweeps ATR multiplier, signal source (own ^NDX vs S&P 500), and T+2 confirmation to find the best real-world configuration — Tables 1-3 above only ever show each strategy at its default parameters.*

> **Best Practice: [fill in from the script's BEST PRACTICE line — strategy, ATR, signal, T+2, and its Avg TWR / Worst DD / Avg Trades].** Picked mechanically: highest Avg TWR among the 33 variants remaining after excluding the 11 deepest-drawdown variants (25%) out of all 44 combinations tested — not a subjective call.

[SMA table from backtest/signal_comparison_output.md, bold the row matching the Best Practice pick if it's SMA]

[EMA table from backtest/signal_comparison_output.md, bold the row matching the Best Practice pick if it's EMA]

> [Commentary blockquote — write this from the actual numbers, answering: (1) Does adding an ATR dead-zone to EMA help at all, comparing the "None" baseline rows to the ATR rows? (2) Does the S&P 500 signal help either strategy family at 3x leverage specifically, consistent with or different from Table 2/3's findings at other tiers? (3) Does T+2 confirmation help or hurt at 3x — Tables 1-3 only show the one T+2 configuration bot.py runs; this table's off/on split answers the question directly for the first time. Cite specific numbers for every claim, the way Table 1-3's blockquotes do — do not assert a qualitative conclusion without checking it against the actual table rows above.]
```

Every bracketed placeholder above must be filled with real, verified content — none of `[...]` may survive into the committed README.

- [ ] **Step 4: Add a CHANGELOG entry**

Add a new entry (matching existing format/style) covering: the `EMACrossover` ATR/T+2 additions (both opt-in, non-breaking), the `strat_backtest.py` helper extraction, the new `generate_signal_comparison.py` script, and the published Table 4 finding (name the actual best-practice pick).

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: add Table 4 — 3x TQQQ signal and parameter comparison (SMA vs EMA)"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = `EMACrossover` engine changes (spec section "EMACrossover Engine Changes"). Task 2 = shared helper extraction (spec section "Shared Helper Extraction"). Task 3 = new script (spec section "New Script"). Task 4 = ranking rule + README output (spec sections "Ranking Rule" and "Output: README.md Table 4"). All spec sections covered.
- **No placeholders in code:** every step has runnable, complete code. The bracketed placeholders in Task 4 Step 3's README template are explicitly flagged as things that must be filled with real content before commit, not left as-is — this is a documentation-content task, not a code placeholder.
- **Behavior-preservation is explicit and testable:** Task 1 Step 3 and Task 2 Step 3 both give concrete before/after commands with stated expected outputs, not just "verify it works."
- **Type/name consistency:** `warmup_aware_start_dates(tickers, period_years)`, `summarize_rolling_results(df_res, strategies, metric_label="TWR")`, `EMACrossover(name, fast_period, slow_period, t2_confirmation, atr_multiplier)` — signatures used identically across Tasks 2, 3, and the design spec.
