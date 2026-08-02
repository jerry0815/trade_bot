# Trailing-Stop Out-of-Sample Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether a trailing-stop candidate selected using only pre-2016 rolling-window history — and separately, the already-published `(8%, 60d)` pick — hold up when evaluated on the untouched 2016-today period never used during selection.

**Architecture:** One new script, `backtest/trailing_stop_out_of_sample.py`, reusing the calendar-cutoff design `backtest/validate_out_of_sample.py` already established. Selection phase: sweep baseline + all 28 `(pct, cooldown)` combinations' rolling Avg TWR improvement over baseline, restricted to the ~44 rolling windows whose 26-year span ends by 2016-01-01, with an automatically-rendered grid-neighbor table so fragility can be judged by inspection (not a rigid re-derived formula — Task 3 of the original plan already showed a purely mechanical neighbor floor can let a cliff through). Evaluation phase: a single non-rolling backtest per variant (29 total) from 2016-01-01 to today, period_years computed dynamically and floored, reported as one ranked table flagging both the pre-2016 selection winner and the published `(8%, 60d)` pick. A finding doc states the verdict.

**Tech Stack:** Python 3.11, pandas — same as the rest of the project. No new dependencies.

**Full design context:** `docs/superpowers/specs/2026-08-02-trailing-stop-out-of-sample-design.md`

## Global Constraints

- **Cutoff is `2016-01-01`** — same cutoff as `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`'s original check.
- **Selection metric is rolling Avg TWR improvement over baseline**, computed only on rolling windows whose full 26-year span ends by the cutoff (`start_date <= 1990-01-01`) — not event-relative decline. This was an explicit user choice over the alternative (event-relative decline on the 3 pre-2016 crises only).
- **Fragility judgment is NOT a rigid formula.** Render every combination's immediate grid-neighbor improvement values alongside it (whichever side(s) exist at grid edges) so a human/report-writer can judge smoothness vs. a cliff by inspection — reusing the same principle as the original plan's Task 3, deliberately without hard-coding a new numeric ratio threshold for this different metric scale.
- **Evaluation phase runs ALL 29 variants unconditionally** (baseline + 28 combinations) regardless of what the selection phase's fragility judgment concludes — the selection-phase judgment only determines which row gets flagged as "the mechanical pick," it does not gate what gets evaluated.
- **`period_years` for the evaluation phase must be computed dynamically** as `int((pd.Timestamp.today() - CUTOFF).days / 365.25)`, **floored to a whole integer** — reusing the exact constraint already derived and documented in `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md` (`Backtester.__init__`'s `pd.DateOffset(years=...)` raises `ValueError` on a fractional value; a non-floored value would also overshoot today and trip `Backtester.run()`'s 98%-span window-length-validation check). Do not re-derive this from scratch or "fix" it by rounding up.
- **Reuse, don't duplicate.** `SMATrendFollowing`, `Backtester`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` must be imported from `backtest.strat_backtest`, not redefined. No changes to any engine file.
- **No change to `bot.py`, live trading behavior, `README.md`, or `CHANGELOG.md`.**

---

### Task 1: Write `backtest/trailing_stop_out_of_sample.py`

**Files:**
- Create: `backtest/trailing_stop_out_of_sample.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `SMATrendFollowing`, `Backtester`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` from `backtest.strat_backtest`.
- Produces: prints and writes `backtest/trailing_stop_out_of_sample_output.md` — a selection-phase table (28 combinations × improvement + neighbor columns) and an evaluation-phase table (29 variants ranked by out-of-sample TWR, with the pre-2016 winner and the published `(8%, 60d)` pick flagged).

- [ ] **Step 1: Write the script**

```python
"""
Out-of-sample validation for the trailing-stop mechanism (see
docs/superpowers/specs/2026-08-02-trailing-stop-out-of-sample-design.md).
Reuses the calendar-cutoff design from backtest/validate_out_of_sample.py
(docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md):
selects a (pct, cooldown) candidate using only rolling windows whose
26-year span ends by CUTOFF, then evaluates baseline + all 28 combinations
on a single non-rolling backtest over the untouched CUTOFF-to-today period.

Run manually:
    python backtest/trailing_stop_out_of_sample.py
"""
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    SMATrendFollowing, Backtester, run_experiment_suite,
    warmup_aware_start_dates, summarize_rolling_results,
)

OUTPUT_PATH = REPO_ROOT / "backtest" / "trailing_stop_out_of_sample_output.md"

BASE_TICKER = "^NDX"
SIGNAL_TICKER = "^GSPC"
CONFIG = {"name": "3x", "leverage": 3, "expense": 0.0095}
PERIOD_YEARS = 26

CUTOFF = pd.Timestamp("2016-01-01")

PCT_GRID = [0.05, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20]
COOLDOWN_GRID = [10, 20, 40, 60]

# Today's already-published candidate (docs/trailing-stop-loss-finding-2026-08-01.md),
# selected using the full, un-split history -- flagged separately from
# whatever this script's pre-2016-only selection phase picks.
PUBLISHED_PCT = 0.08
PUBLISHED_COOLDOWN = 60


def make_strategy(pct=None, cooldown=None):
    if pct is None:
        return SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    return SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True,
                              trailing_stop_pct=pct, trailing_stop_cooldown_days=cooldown)


def build_variants():
    """[(pct, cooldown, strategy), ...] -- (None, None, ...) is baseline, first entry."""
    variants = [(None, None, make_strategy())]
    for pct in PCT_GRID:
        for cooldown in COOLDOWN_GRID:
            variants.append((pct, cooldown, make_strategy(pct, cooldown)))
    return variants


def selection_start_dates():
    """Windows whose full PERIOD_YEARS-year span ends by CUTOFF -- no calendar
    overlap with the CUTOFF-to-today evaluation period."""
    all_dates = warmup_aware_start_dates([BASE_TICKER, SIGNAL_TICKER], PERIOD_YEARS)
    max_start = CUTOFF - pd.DateOffset(years=PERIOD_YEARS)
    return all_dates[all_dates <= max_start]


def run_selection_phase(variants, start_dates):
    """Returns ({(pct, cooldown): avg_twr}, n_windows_actually_used), using
    ONLY the given (pre-cutoff) start_dates."""
    strategies = [strat for _, _, strat in variants]
    results = run_experiment_suite(
        configs=[CONFIG], strategies=strategies, start_dates=start_dates,
        period_years=PERIOD_YEARS, base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
        print_summary=False,
    )
    df_res = results[CONFIG["name"]]
    summary = summarize_rolling_results(df_res, strategies)
    # summarize_rolling_results iterates `strategies` in order and appends one
    # row per strategy, so zip(variants, summary) aligns positionally.
    twr_by_key = {}
    for (pct, cooldown, _), row in zip(variants, summary):
        twr_by_key[(pct, cooldown)] = row["Avg TWR"]
    return twr_by_key, len(df_res)


def grid_neighbor_values(twr_by_key, baseline_twr, pct, cooldown):
    """Improvement-over-baseline for the immediate grid-adjacent pct and
    cooldown values (whichever side(s) exist -- grid edges only have one)."""
    pct_idx = PCT_GRID.index(pct)
    cooldown_idx = COOLDOWN_GRID.index(cooldown)
    pct_neighbors = []
    for i in (pct_idx - 1, pct_idx + 1):
        if 0 <= i < len(PCT_GRID):
            n_pct = PCT_GRID[i]
            pct_neighbors.append((n_pct, cooldown, twr_by_key[(n_pct, cooldown)] - baseline_twr))
    cooldown_neighbors = []
    for i in (cooldown_idx - 1, cooldown_idx + 1):
        if 0 <= i < len(COOLDOWN_GRID):
            n_cd = COOLDOWN_GRID[i]
            cooldown_neighbors.append((pct, n_cd, twr_by_key[(pct, n_cd)] - baseline_twr))
    return pct_neighbors, cooldown_neighbors


def render_selection_table(twr_by_key, n_windows):
    baseline_twr = twr_by_key[(None, None)]
    rows = []
    for pct in PCT_GRID:
        for cooldown in COOLDOWN_GRID:
            improvement = twr_by_key[(pct, cooldown)] - baseline_twr
            pct_n, cd_n = grid_neighbor_values(twr_by_key, baseline_twr, pct, cooldown)
            rows.append({"pct": pct, "cooldown": cooldown, "improvement": improvement,
                         "pct_neighbors": pct_n, "cooldown_neighbors": cd_n})
    rows.sort(key=lambda r: -r["improvement"])

    def fmt_neighbors(neighbors):
        if not neighbors:
            return "n/a"
        return "; ".join(f"({p:.0%},{c}d)={v:+.2f}pp" for p, c, v in neighbors)

    lines = [f"### Selection Phase: Pre-{CUTOFF.date()} Rolling Avg TWR Improvement over Baseline ({n_windows} windows)", "",
             f"Baseline (no trailing stop) selection-phase Avg TWR: {baseline_twr:.2f}%", "",
             "| Pct | Cooldown | Improvement (pp) | Pct-neighbor(s) | Cooldown-neighbor(s) |",
             "| ---: | ---: | ---: | :--- | :--- |"]
    for r in rows:
        lines.append(
            f"| {r['pct']:.0%} | {r['cooldown']}d | {r['improvement']:+.2f} "
            f"| {fmt_neighbors(r['pct_neighbors'])} | {fmt_neighbors(r['cooldown_neighbors'])} |"
        )
    top = rows[0]
    return "\n".join(lines), top


def run_evaluation_phase(variants):
    """Single non-rolling backtest, CUTOFF to today, for every variant.
    period_years is floored to a whole integer -- Backtester.__init__'s
    pd.DateOffset(years=...) raises ValueError on a fractional value, and a
    non-floored value would overshoot today, tripping Backtester.run()'s
    98%-span window-length-validation check (no future data exists to fill
    a longer request). See docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md
    for the original derivation of this constraint -- reused verbatim here."""
    period_years = int((pd.Timestamp.today() - CUTOFF).days / 365.25)
    rows = []
    for pct, cooldown, strat in variants:
        env = Backtester(
            base_ticker=BASE_TICKER, signal_ticker=SIGNAL_TICKER,
            start_date=CUTOFF.strftime("%Y-%m-%d"), period_years=period_years,
            leverage=CONFIG["leverage"], expense_ratio=CONFIG["expense"],
            initial_fund=10000, apply_tax=False, verbose=False,
        )
        res = env.run(strat)
        if res is None:
            continue
        rows.append({
            "pct": pct, "cooldown": cooldown,
            "TWR": res["strategy_twr"], "Max DD": res["max_drawdown"],
            "Trades": res.get("total_trades", 0),
        })
    return rows, period_years


def render_evaluation_table(eval_rows, selection_top):
    rows_sorted = sorted(eval_rows, key=lambda r: -r["TWR"])
    lines = ["### Evaluation Phase: Out-of-Sample Single Backtest (CUTOFF-to-today)", "",
             "| Pct | Cooldown | TWR | Max DD | Trades | |",
             "| ---: | ---: | ---: | ---: | ---: | :--- |"]
    for rank, r in enumerate(rows_sorted, 1):
        pct_label = "baseline" if r["pct"] is None else f"{r['pct']:.0%}"
        cd_label = "-" if r["cooldown"] is None else f"{r['cooldown']}d"
        markers = []
        if r["pct"] == selection_top["pct"] and r["cooldown"] == selection_top["cooldown"]:
            markers.append("<- PRE-2016 SELECTION-PHASE WINNER")
        if r["pct"] == PUBLISHED_PCT and r["cooldown"] == PUBLISHED_COOLDOWN:
            markers.append("<- PUBLISHED (8%, 60d) PICK")
        marker = " ".join(markers)
        lines.append(
            f"| {pct_label} | {cd_label} | {r['TWR']:.2f}% | {r['Max DD']:.2f}% "
            f"| {r['Trades']:.0f} | rank #{rank}/{len(rows_sorted)} {marker} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    variants = build_variants()

    print(f"CUTOFF: {CUTOFF.date()} | today: {pd.Timestamp.today().date()}")
    sel_dates = selection_start_dates()
    print(f"Selection phase: {len(variants)} variants, {len(sel_dates)} windows ending by {CUTOFF.date()}...")
    twr_by_key, n_sel_windows = run_selection_phase(variants, sel_dates)
    selection_table, selection_top = render_selection_table(twr_by_key, n_sel_windows)
    print("\n" + selection_table)
    print(f"\nMechanical top pick: ({selection_top['pct']:.0%}, {selection_top['cooldown']}d), "
          f"improvement {selection_top['improvement']:+.2f}pp -- inspect the neighbor columns above "
          f"for fragility before trusting this at face value.")

    print(f"\nEvaluation phase: {len(variants)} variants, single run {CUTOFF.date()} to today...")
    eval_rows, eval_period_years = run_evaluation_phase(variants)
    evaluation_table = render_evaluation_table(eval_rows, selection_top)
    print("\n" + evaluation_table)

    output = "\n\n".join([selection_table, evaluation_table])
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nWritten to {OUTPUT_PATH}")
```

- [ ] **Step 2: Smoke-test the selection-phase date filtering before the full run**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.trailing_stop_out_of_sample import selection_start_dates
dates = selection_start_dates()
print('selection windows:', len(dates), '| range:', dates[0].date(), 'to', dates[-1].date())
"
```
Expected: a window count in the low-to-mid 40s (matching `docs/superpowers/specs/2026-07-28-out-of-sample-validation-design.md`'s original ~44-window estimate for the same cutoff and tickers — exact count depends on today's date, should be well under 100), with the range ending on or before `1990-01-01`. If the range extends past `1990-01-01`, the filter has a bug — stop and investigate before running the full script.

- [ ] **Step 3: Smoke-test one variant end-to-end (both phases) before the full 29-variant run**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from backtest.trailing_stop_out_of_sample import build_variants, selection_start_dates, run_selection_phase, run_evaluation_phase
variants = build_variants()[:2]  # baseline + (5%, 10d) only
sel_dates = selection_start_dates()
twr_by_key, n = run_selection_phase(variants, sel_dates)
print('selection twr_by_key:', twr_by_key, '| n_windows:', n)
eval_rows, period_years = run_evaluation_phase(variants)
print('eval_rows:', eval_rows, '| period_years:', period_years)
"
```
Expected: `twr_by_key` prints two real (not NaN/None) Avg TWR values; `eval_rows` prints two dicts with real `TWR`/`Max DD`/`Trades` values, no traceback. `period_years` should be a plausible integer (roughly `today's year - 2016`, e.g. 10 or 11 depending on today's date). This confirms both phases work end-to-end before committing to the full 29-variant run.

- [ ] **Step 4: Add the scratch output file to `.gitignore`**

Append to `.gitignore`:
```
backtest/trailing_stop_out_of_sample_output.md
```

- [ ] **Step 5: Commit**

```bash
git add backtest/trailing_stop_out_of_sample.py .gitignore
git commit -m "feat: add trailing-stop out-of-sample validation script"
```

---

### Task 2: Run the full validation, sanity-check, and record the selection judgment

**Files:** none (this task only runs Task 1's script and inspects/interprets output).

- [ ] **Step 1: Run the full validation**

```bash
python backtest/trailing_stop_out_of_sample.py
```
Expect no tracebacks, both tables printed, and a final "Written to backtest/trailing_stop_out_of_sample_output.md" line. The selection phase runs 29 strategies across ~44 windows (more total backtests than Task 4's original 172-window×2-strategy rolling validation) — budget several minutes, this is expected to take a while, not a hang.

- [ ] **Step 2: Sanity-check the evaluation-phase baseline row against an independent published reference**

Read `backtest/trailing_stop_out_of_sample_output.md`'s evaluation table. The `baseline` row (pct=`baseline`, cooldown=`-`) should closely match a row **already published** in this project's prior out-of-sample check — `docs/out-of-sample-validation-2026-07-28.md`'s SMA out-of-sample evaluation table has a row for this exact config (SMA, ATR x2.5, S&P 500 signal, T+2 On), evaluated on the same 2016-cutoff period:

> `x2.5 | S&P 500 (^GSPC) | On | 19.20% | -72.26% | 5`

Confirm the new baseline row's TWR/Max DD/Trades are close to `19.20%` / `-72.26%` / `5` (small differences are fine — that doc was generated 2026-07-28, a few days of data/date drift could shift things slightly; an order-of-magnitude or sign difference means something is broken in this script, not a real finding — investigate before proceeding).

- [ ] **Step 3: Sanity-check the selection-phase window count**

Confirm the selection table's window count (in its header, e.g. "(44 windows)") matches Step 2 of Task 1's smoke test — should be the same number, since both call `selection_start_dates()`.

- [ ] **Step 4: Apply the fragility judgment to the selection-phase table**

Read the full selection-phase table (28 rows, sorted by improvement). Identify the mechanical top pick (already flagged in the script's own printed output) and inspect its `Pct-neighbor(s)` and `Cooldown-neighbor(s)` columns:
- If the neighbor values are the same order of magnitude as the top pick's own improvement (not a several-times-larger jump — the same principle the original plan's Task 3 used, e.g. a neighbor scoring 20-50% of the top value or more is smooth; a neighbor scoring under ~10% of it, or negative, while the top value is large, is a cliff), the pre-2016 selection is trustworthy as stated.
- If it shows the same non-monotonic-cliff pattern this project has flagged three times now (Table 4's ATR sweep, Phase 6's `atr_spike_multiplier`, and this same investigation's own `(5%, 60d)` rejection in Task 3), note that explicitly and identify the next-best candidate whose neighborhood is smooth instead — same reasoning process as the original Task 3, applied fresh to this new table. Show your work: state the top few candidates' neighbor values explicitly in your notes for Task 3 to use.

Record your conclusion (which `(pct, cooldown)` — if any — is the trustworthy pre-2016 selection-phase winner, and why) for use in the next task.

- [ ] **Step 5: Read the evaluation-phase ranking for both flagged rows**

Note the rank (out of 29) and TWR/Max DD for:
- The pre-2016 selection-phase winner from Step 4 (marked `<- PRE-2016 SELECTION-PHASE WINNER` in the table if it matches the script's mechanical top pick; if Step 4 concluded a *different* combination is the trustworthy pick, find that row manually instead).
- The published `(8%, 60d)` pick (marked `<- PUBLISHED (8%, 60d) PICK`).

---

### Task 3: Write the out-of-sample finding

**Files:**
- Create: `docs/trailing-stop-loss-out-of-sample-2026-08-02.md`

- [ ] **Step 1: Write the finding doc**

Structure the doc with these sections, sourcing every number from `backtest/trailing_stop_out_of_sample_output.md` and Task 2's recorded conclusions — don't invent or approximate anything not present there.

- **Method** — one paragraph summarizing the calendar-cutoff split (cite `docs/superpowers/specs/2026-08-02-trailing-stop-out-of-sample-design.md` for full rationale, don't repeat it all), and one sentence noting the sanity check against `docs/out-of-sample-validation-2026-07-28.md`'s independently-published baseline row passed (or didn't — state plainly if it didn't and what was investigated).
- **Selection Result** — the mechanical top pick, its neighbor values, and the fragility judgment from Task 2 Step 4 (trustworthy as-is, or a different combination identified as the real pick, with reasoning).
- **Evaluation Result** — where the pre-2016 selection-phase winner and the published `(8%, 60d)` pick each rank among all 29 variants out-of-sample, with their TWR/Max DD compared to the selection-phase numbers that motivated picking them. State plainly whether this looks like generalization (a good out-of-sample rank, e.g. top third) or the Table 4 precedent repeating (a poor rank despite a strong in-sample story — cite `docs/out-of-sample-validation-2026-07-28.md`'s #30-of-44 result by name as the comparison point).
- **Verdict** — an honest recommendation given everything validated across both this doc and `docs/trailing-stop-loss-finding-2026-08-01.md`: is the trailing-stop mechanism now ready to recommend for `bot.py` adoption, or does it need further work (and if so, what specifically) — driven by what the numbers actually show, not decided in advance. If the out-of-sample result is weak, say so plainly, the same way `docs/out-of-sample-validation-2026-07-28.md` did for its own pick.

- [ ] **Step 2: Commit**

```bash
git add docs/trailing-stop-loss-out-of-sample-2026-08-02.md
git commit -m "docs: add trailing-stop out-of-sample validation finding"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = design's "Mechanism" + "Components §1" (the script, selection phase with neighbor rendering, evaluation phase with dynamic `period_years`). Task 2 = running it + the design's "candidate selection procedure" steps 3-5 (shortlist/judgment, not gating downstream computation since evaluation is unconditional) + the sanity-check convention established across every prior analysis script in this project. Task 3 = "Components §2" (finding write-up). The "Explicitly out of scope" items (commission/slippage check, `bot.py`/README changes, re-deriving `period_years` mechanics, a second cutoff/walk-forward) are correctly absent from every task.
- **No placeholders:** every step has runnable code or an exact, mechanical instruction with stated expected output (including the independently-published sanity-check reference number, sourced from a file read during plan-writing, not invented). Task 2 Step 4's fragility judgment is deliberately not reduced to a rigid formula — per the design spec's explicit reasoning (a prior rigid formula let a cliff through) — but gives a concrete worked heuristic (order-of-magnitude comparison) and requires showing the reasoning, which is a fully-specified process even though its outcome isn't predetermined.
- **Type/name consistency:** `build_variants()`, `selection_start_dates()`, `run_selection_phase(variants, start_dates)`, `grid_neighbor_values(twr_by_key, baseline_twr, pct, cooldown)`, `render_selection_table(twr_by_key, n_windows)`, `run_evaluation_phase(variants)`, `render_evaluation_table(eval_rows, selection_top)` used identically throughout Task 1 and referenced correctly in Task 1's own smoke-test steps. `SMATrendFollowing`, `Backtester`, `run_experiment_suite`, `warmup_aware_start_dates`, `summarize_rolling_results` imported with their real, current signatures (verified by reading `backtest/strat_backtest.py` and `backtest/trailing_stop_validate.py` directly while writing this plan). The independently-published sanity-check row (`x2.5 | S&P 500 (^GSPC) | On | 19.20% | -72.26% | 5`) was read directly from `docs/out-of-sample-validation-2026-07-28.md` while writing this plan, not recalled from memory.
