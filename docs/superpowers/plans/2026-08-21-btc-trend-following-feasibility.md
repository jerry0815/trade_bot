# BTC Trend-Following Feasibility Study — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine — honestly, with "inconclusive" allowed — whether the project's untuned equity trend rule (SMA 200 + ATR ×2.5, ± an 8%/60d trailing stop) transfers to spot Bitcoin, judged against a pre-registered pass/fail bar.

**Architecture:** A single-path screen script (`backtest/btc_trend_screen.py`) that reuses the existing `strat_backtest.py` engine verbatim — no new signal code. It runs `BuyAndHold`, core, and core+stop on `BTC-USD` at leverage 1, then reports a headline KPI table, a per-cycle drawdown table, a parameter-plateau surface, and an untuned cross-asset replication (ETH/LTC). A pure verdict function applies the §5 thresholds. A writeup doc records the pre-registered bar and the verdict.

**Tech Stack:** Python, pandas, numpy, yfinance (all already in the repo). Reuses `Backtester`, `SMATrendFollowing`, `BuyAndHold`, `get_cached_signals`, and the `calmar` / `sharpe_from_equity` helpers.

## Global Constraints

- **No BTC tuning.** All strategy parameters are inherited unchanged from equities: `sma_window=200`, `atr_multiplier=2.5`, `trailing_stop_pct=0.08`, `trailing_stop_cooldown_days=60`. The plateau surface (Task 5) is a robustness check, **never** used to pick a BTC-best parameter set.
- **Spot BTC only:** `leverage=1`, `expense_ratio=0.0` (holding spot has no ER; leverage 1 means no borrow drag).
- **Single continuous path.** No rolling-window table — that would manufacture cosmetic window count from ~3 shared cycles. The per-cycle table is the disaggregation.
- **Pre-registration.** The §5 pass/fail thresholds are fixed in the spec *before* results and are quoted verbatim in the writeup, dated before the numbers.
- **Unit tests are network-free** (synthetic frames), matching repo convention (`tests/test_vol_target_leverage.py`). Real BTC data validation is a runtime check printed by the screen, not a pytest test.
- **Data reality (discovered during planning):** `BTC-USD` on yfinance starts ~2014-09-17. That means only **2 fully in-sample bear cycles (2018, 2021-22)**; the 2014-15 bear's peak predates the data, so it is a **partial** cycle (tail only). The per-cycle table labels it `partial`. Effective N ≈ 2.5, not 3 — the writeup states this plainly.
- Spec: [docs/superpowers/specs/2026-08-21-btc-trend-following-feasibility-design.md](../specs/2026-08-21-btc-trend-following-feasibility-design.md).

---

### Task 1: Cycle constants + per-cycle max-drawdown function

The one piece of genuinely new logic worth isolating and unit-testing: slicing an equity curve to a date window and computing its peak-to-trough drawdown. Pure, network-free.

**Files:**
- Create: `backtest/btc_trend_screen.py`
- Test: `tests/test_btc_trend_screen.py`

**Interfaces:**
- Produces:
  - `BTC_CYCLES: list[dict]` — each `{"name": str, "start": str, "end": str, "partial": bool}`.
  - `cycle_max_drawdown(equity: pd.Series, start: str, end: str) -> float` — worst peak-to-trough return within `[start, end]`, as a fraction ≤ 0 (e.g. `-0.77`). Returns `float("nan")` if the slice is empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_btc_trend_screen.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.btc_trend_screen import cycle_max_drawdown, BTC_CYCLES


def test_cycle_max_drawdown_basic_peak_to_trough():
    # equity 100 -> 120 (peak) -> 60 (trough) -> 90, within the window.
    # worst peak-to-trough = 60/120 - 1 = -0.5
    idx = pd.date_range("2018-01-01", periods=4, freq="D")
    eq = pd.Series([100.0, 120.0, 60.0, 90.0], index=idx)
    dd = cycle_max_drawdown(eq, "2018-01-01", "2018-01-04")
    assert abs(dd - (-0.5)) < 1e-9


def test_cycle_max_drawdown_respects_window_bounds():
    # A crash OUTSIDE the window must not count.
    idx = pd.date_range("2018-01-01", periods=5, freq="D")
    eq = pd.Series([100.0, 100.0, 100.0, 100.0, 10.0], index=idx)
    dd = cycle_max_drawdown(eq, "2018-01-01", "2018-01-03")
    assert abs(dd - 0.0) < 1e-9


def test_cycle_max_drawdown_empty_slice_is_nan():
    idx = pd.date_range("2018-01-01", periods=2, freq="D")
    eq = pd.Series([100.0, 90.0], index=idx)
    assert np.isnan(cycle_max_drawdown(eq, "2020-01-01", "2020-02-01"))


def test_btc_cycles_are_well_formed():
    assert len(BTC_CYCLES) == 3
    names = [c["name"] for c in BTC_CYCLES]
    assert any("2018" in n for n in names)
    assert any("2022" in n for n in names)
    # the 2014-15 cycle is flagged partial (peak predates BTC-USD data)
    partial = [c for c in BTC_CYCLES if c["partial"]]
    assert len(partial) == 1 and "2014" in partial[0]["name"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_btc_trend_screen.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'cycle_max_drawdown'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backtest/btc_trend_screen.py
"""Single-path feasibility screen: does the untuned equity trend rule transfer
to spot Bitcoin? Runs BuyAndHold / core / core+stop on BTC-USD (leverage 1,
pre-tax), reports a headline KPI table, a per-cycle drawdown table, a parameter
-plateau surface, and an untuned ETH/LTC cross-asset replication, then applies a
pre-registered pass/fail bar. Feasibility study — "inconclusive" is a valid
outcome. See docs/superpowers/specs/2026-08-21-btc-trend-following-feasibility-design.md

Run:
    python backtest/btc_trend_screen.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# BTC drawdown cycles. 2014-15's PEAK (~2013-11, ~$1150) predates BTC-USD's
# yfinance history (~2014-09-17), so it is a PARTIAL cycle: we see only the tail
# down to the ~2015-01 bottom. 2018 and 2021-22 are fully in-sample.
BTC_CYCLES = [
    {"name": "2014-15 (partial)", "start": "2014-09-17", "end": "2015-01-31", "partial": True},
    {"name": "2018",             "start": "2017-12-17", "end": "2018-12-31", "partial": False},
    {"name": "2021-22",          "start": "2021-11-10", "end": "2022-11-30", "partial": False},
]


def cycle_max_drawdown(equity, start, end):
    """Worst peak-to-trough return within [start, end], as a fraction <= 0.

    equity: daily equity pd.Series indexed by date. Returns nan for an empty slice.
    """
    window = equity.loc[str(start):str(end)]
    if window.empty:
        return float("nan")
    running_peak = window.cummax()
    drawdown = window / running_peak - 1.0
    return float(drawdown.min())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_btc_trend_screen.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backtest/btc_trend_screen.py tests/test_btc_trend_screen.py
git commit -m "feat(btc): cycle constants + per-cycle max-drawdown helper"
```

---

### Task 2: Verdict classifier against the pre-registered bar

The §5 pass/fail logic as a pure function — the honesty core of the study. Network-free, fully unit-tested against the thresholds.

**Files:**
- Modify: `backtest/btc_trend_screen.py`
- Test: `tests/test_btc_trend_screen.py`

**Interfaces:**
- Consumes: nothing external.
- Produces: `classify_verdict(dd_reduction_pp, cagr_giveup_frac, calmar_strategy, calmar_bh, plateau_ok) -> str`
  - `dd_reduction_pp: list[float]` — per-cycle drawdown reduction in **percentage points** (strategy DD minus buy-&-hold DD, sign such that a *positive* value = shallower/ better; only the 3 cycles, partial included).
  - `cagr_giveup_frac: float` — `1 - strategy_cagr / bh_cagr` (fraction of buy-&-hold CAGR given up).
  - `calmar_strategy`, `calmar_bh: float`.
  - `plateau_ok: bool` — from Task 5.
  - Returns one of `"PASS"`, `"FAIL"`, `"INCONCLUSIVE"`.

Thresholds (verbatim from spec §5): PASS = drawdown cut ≥20pp in ≥2 of 3 cycles AND CAGR give-up ≤30% AND plateau_ok. FAIL = drawdown cut fails (<20pp) in ≥2 of 3 cycles OR Calmar worse than buy-&-hold. Else INCONCLUSIVE.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_btc_trend_screen.py
from backtest.btc_trend_screen import classify_verdict


def test_verdict_pass_all_conditions_met():
    # 3/3 cycles cut DD by >=20pp, gave up 10% CAGR, plateau ok, calmar better
    v = classify_verdict([25.0, 30.0, 22.0], 0.10, 1.2, 0.4, True)
    assert v == "PASS"


def test_verdict_fail_drawdown_not_reduced_in_two_cycles():
    # only 1 cycle clears 20pp -> fails in 2 of 3
    v = classify_verdict([25.0, 5.0, 3.0], 0.10, 1.2, 0.4, True)
    assert v == "FAIL"


def test_verdict_fail_calmar_worse_than_bh():
    # DD reduced well but calmar worse than buy-and-hold -> FAIL
    v = classify_verdict([25.0, 30.0, 22.0], 0.10, 0.30, 0.40, True)
    assert v == "FAIL"


def test_verdict_inconclusive_knife_edge_plateau():
    # DD + return fine, but params sit on a spike (plateau_ok False) -> not PASS,
    # and calmar is better so not FAIL -> INCONCLUSIVE
    v = classify_verdict([25.0, 30.0, 22.0], 0.10, 1.2, 0.4, False)
    assert v == "INCONCLUSIVE"


def test_verdict_inconclusive_return_giveup_too_high_but_calmar_ok():
    # gave up 45% CAGR (>30% -> not PASS), but calmar still >= bh -> INCONCLUSIVE
    v = classify_verdict([25.0, 30.0, 22.0], 0.45, 0.50, 0.40, True)
    assert v == "INCONCLUSIVE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_btc_trend_screen.py -k verdict -v`
Expected: FAIL with `ImportError: cannot import name 'classify_verdict'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backtest/btc_trend_screen.py
def classify_verdict(dd_reduction_pp, cagr_giveup_frac, calmar_strategy,
                     calmar_bh, plateau_ok):
    """Apply the pre-registered §5 bar. dd_reduction_pp: per-cycle (strategy DD
    shallower than buy-&-hold) in percentage points; positive = better."""
    cycles_helped = sum(1 for r in dd_reduction_pp if r >= 20.0)
    cycles_failed = sum(1 for r in dd_reduction_pp if r < 20.0)

    # FAIL takes precedence: drawdown protection broke, or risk-adjusted return
    # is outright worse than just holding BTC.
    if cycles_failed >= 2 or calmar_strategy < calmar_bh:
        return "FAIL"

    if cycles_helped >= 2 and cagr_giveup_frac <= 0.30 and plateau_ok:
        return "PASS"

    return "INCONCLUSIVE"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_btc_trend_screen.py -v`
Expected: PASS (9 passed total).

- [ ] **Step 5: Commit**

```bash
git add backtest/btc_trend_screen.py tests/test_btc_trend_screen.py
git commit -m "feat(btc): pre-registered pass/fail verdict classifier"
```

---

### Task 3: Data span helper + config runner + headline KPI table

Glue the engine to BTC: compute the full-history window (avoiding the engine's 98%-coverage rejection), run the three configs, and produce the headline KPI table. Reuses the `_kpis` / `_run` pattern from `vol_target_screen.py`.

**Files:**
- Modify: `backtest/btc_trend_screen.py`
- Test: `tests/test_btc_trend_screen.py`

**Interfaces:**
- Consumes: `Backtester`, `SMATrendFollowing`, `BuyAndHold`, `get_cached_signals` from `strat_backtest`; `calmar`, `sharpe_from_equity` from `dynamic_leverage_screen`.
- Produces:
  - `btc_span(ticker="BTC-USD") -> tuple[str, int]` — returns `(start_date_str, period_years)` covering the ticker's full available history (period_years = floor of the actual span in years, min 1), so `Backtester`'s coverage check passes.
  - `run_config(strategy, ticker="BTC-USD") -> dict | None` — runs one strategy on spot `ticker` (leverage 1, ER 0, verbose off) and returns a KPI dict `{"cagr","max_dd","calmar","sharpe","trades","equity_curve"}`, or `None` if the engine rejects the window.
  - `CONFIGS: list[tuple[str, callable]]` — the three named factories: `("Buy & Hold BTC", BuyAndHold)`, `("Core (SMA200+ATR2.5)", lambda: SMATrendFollowing(atr_multiplier=2.5))`, `("Core + Stop (8%/60d)", lambda: SMATrendFollowing(atr_multiplier=2.5, trailing_stop_pct=0.08, trailing_stop_cooldown_days=60))`.

- [ ] **Step 1: Write the failing test** (network-free: `btc_span` on a synthetic frame via monkeypatch)

```python
# append to tests/test_btc_trend_screen.py
import backtest.btc_trend_screen as bts


def test_btc_span_computes_full_history_window(monkeypatch):
    # ~12.0 years of daily dates -> start = first date, period_years = 12
    idx = pd.date_range("2014-09-17", "2026-09-16", freq="D")
    fake = pd.DataFrame({"Close": np.arange(len(idx), dtype=float)}, index=idx)
    monkeypatch.setattr(bts, "get_cached_signals", lambda ticker="BTC-USD": fake)
    start, years = bts.btc_span("BTC-USD")
    assert start == "2014-09-17"
    assert years == 12


def test_btc_span_minimum_one_year(monkeypatch):
    idx = pd.date_range("2024-01-01", "2024-06-01", freq="D")
    fake = pd.DataFrame({"Close": np.arange(len(idx), dtype=float)}, index=idx)
    monkeypatch.setattr(bts, "get_cached_signals", lambda ticker="BTC-USD": fake)
    _, years = bts.btc_span("BTC-USD")
    assert years == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_btc_trend_screen.py -k span -v`
Expected: FAIL with `AttributeError: module 'backtest.btc_trend_screen' has no attribute 'btc_span'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backtest/btc_trend_screen.py (add imports at top of file)
from backtest.strat_backtest import (Backtester, SMATrendFollowing, BuyAndHold,
                                      get_cached_signals)
from backtest.dynamic_leverage_screen import calmar, sharpe_from_equity

CONFIGS = [
    ("Buy & Hold BTC",         BuyAndHold),
    ("Core (SMA200+ATR2.5)",   lambda: SMATrendFollowing(atr_multiplier=2.5)),
    ("Core + Stop (8%/60d)",   lambda: SMATrendFollowing(
        atr_multiplier=2.5, trailing_stop_pct=0.08, trailing_stop_cooldown_days=60)),
]


def btc_span(ticker="BTC-USD"):
    """(start_date_str, period_years) covering the ticker's full history, sized
    so Backtester's 98%-coverage check accepts the whole available series."""
    df = get_cached_signals(ticker)
    first, last = df.index.min(), df.index.max()
    years = max(1, int((last - first).days // 365))
    return first.strftime("%Y-%m-%d"), years


def _kpis(res):
    eq = res["equity_curve"]
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    max_dd = res["max_drawdown"] / 100.0
    return {"cagr": cagr, "max_dd": max_dd, "calmar": calmar(cagr, max_dd),
            "sharpe": sharpe_from_equity(eq), "trades": res.get("total_trades", 0),
            "equity_curve": eq}


def run_config(strategy, ticker="BTC-USD"):
    start, years = btc_span(ticker)
    env = Backtester(base_ticker=ticker, signal_ticker=ticker, start_date=start,
                     period_years=years, leverage=1, expense_ratio=0.0,
                     initial_fund=10000, verbose=False)
    res = env.run(strategy)
    return _kpis(res) if res else None
```

- [ ] **Step 4: Run the span tests, then a live smoke run**

Run: `python -m pytest tests/test_btc_trend_screen.py -k span -v`
Expected: PASS.

Then a quick live check (network — validates BTC-USD flows through the engine and reproduces a known drawdown; ~-77% for 2021-22 buy-&-hold):

```bash
python -c "import backtest.btc_trend_screen as b; k=b.run_config(b.BuyAndHold()); print('CAGR %.1f%%  MaxDD %.1f%%' % (k['cagr']*100, k['max_dd']*100)); print('2021-22 DD %.1f%%' % (b.cycle_max_drawdown(k['equity_curve'],'2021-11-10','2022-11-30')*100))"
```
Expected: buy-&-hold BTC max DD ≈ −80% or deeper; 2021-22 cycle DD ≈ −73% to −78%. If wildly off (e.g. −5% or positive), STOP — the data or wiring is wrong; debug before trusting anything downstream.

- [ ] **Step 5: Commit**

```bash
git add backtest/btc_trend_screen.py tests/test_btc_trend_screen.py
git commit -m "feat(btc): data-span helper + config runner + KPI extraction"
```

---

### Task 4: Assemble the screen — headline table, per-cycle table, output doc

Wire Tasks 1–3 into the runnable screen: print + write a markdown doc with the headline KPI table and the per-cycle drawdown table (strategy vs buy-&-hold, one row per cycle).

**Files:**
- Modify: `backtest/btc_trend_screen.py`

**Interfaces:**
- Consumes: `CONFIGS`, `run_config`, `BTC_CYCLES`, `cycle_max_drawdown`.
- Produces: `build_headline_table(results) -> str`, `build_cycle_table(results) -> str`, `main()`. Writes `backtest/btc_trend_screen_output.md`.
- `results: dict[str, dict|None]` keyed by config name → KPI dict.

- [ ] **Step 1: Implement the tables + main** (no separate unit test — this is formatting glue over already-tested functions; validated by running it)

```python
# append to backtest/btc_trend_screen.py
OUTPUT_PATH = REPO_ROOT / "backtest" / "btc_trend_screen_output.md"


def build_headline_table(results):
    head = ("| Config | CAGR | Worst DD | Calmar | Sharpe | Trades |\n"
            "| :--- | ---: | ---: | ---: | ---: | ---: |\n")
    body = ""
    for name, _ in CONFIGS:
        k = results.get(name)
        if k is None:
            body += f"| {name} | — | — | — | — | — |\n"
            continue
        body += (f"| {name} | {k['cagr']*100:.2f}% | {k['max_dd']*100:.2f}% | "
                 f"{k['calmar']:.2f} | {k['sharpe']:.2f} | {k['trades']} |\n")
    return head + body


def build_cycle_table(results):
    bh = results.get("Buy & Hold BTC")
    head = ("| Cycle | Buy & Hold DD | Core DD | Core+Stop DD | Best reduction (pp) |\n"
            "| :--- | ---: | ---: | ---: | ---: |\n")
    body = ""
    for c in BTC_CYCLES:
        def dd(name):
            k = results.get(name)
            return cycle_max_drawdown(k["equity_curve"], c["start"], c["end"]) if k else float("nan")
        bh_dd, core_dd, stop_dd = dd("Buy & Hold BTC"), dd("Core (SMA200+ATR2.5)"), dd("Core + Stop (8%/60d)")
        # reduction in pp: how much shallower the better strategy DD is vs B&H
        best_strat_dd = max(core_dd, stop_dd)  # closer to 0 = shallower
        reduction = (best_strat_dd - bh_dd) * 100.0  # positive = shallower than B&H
        label = c["name"] + (" ⚠" if c["partial"] else "")
        body += (f"| {label} | {bh_dd*100:.1f}% | {core_dd*100:.1f}% | "
                 f"{stop_dd*100:.1f}% | {reduction:+.1f} |\n")
    return head + body


def main():
    results = {name: run_config(factory()) for name, factory in CONFIGS}
    headline = build_headline_table(results)
    cycles = build_cycle_table(results)
    note = ("\n> **Feasibility screen — single continuous BTC-USD path (spot, 1x, "
            "pre-tax), untuned equity params.** No rolling windows (only ~2.5 "
            "in-sample cycles; the 2014-15 peak predates BTC-USD data, marked ⚠ "
            "partial). Per-cycle reduction is in percentage points, positive = "
            "shallower than buy-&-hold. See the writeup for the pre-registered "
            "verdict.\n")
    doc = (f"# Bitcoin Trend-Following — Feasibility Screen\n\n"
           f"## Headline (full path)\n\n{headline}\n"
           f"## Per-cycle max drawdown\n\n{cycles}{note}")
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    print(doc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the screen end-to-end**

Run: `python backtest/btc_trend_screen.py`
Expected: prints the two tables and writes `backtest/btc_trend_screen_output.md`. Sanity-check: Buy & Hold DD ≈ −80%+; Core/Core+Stop DDs shallower in at least the 2018 and 2021-22 rows; numbers finite (no NaN in the 2018 / 2021-22 rows).

- [ ] **Step 3: Run the full test file to confirm nothing regressed**

Run: `python -m pytest tests/test_btc_trend_screen.py -v`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add backtest/btc_trend_screen.py
git commit -m "feat(btc): assemble screen — headline + per-cycle drawdown tables"
```

---

### Task 5: Parameter-plateau surface (robustness, not optimization)

Confirm the inherited params sit on a smooth plateau, not a lucky spike. Sweep `atr_multiplier` and `sma_window` in a neighborhood around the inherited values and report the metric surface. Derive `plateau_ok` for the verdict.

**Files:**
- Modify: `backtest/btc_trend_screen.py`
- Test: `tests/test_btc_trend_screen.py`

**Interfaces:**
- Produces:
  - `plateau_ok(surface, center_key, metric="calmar", tol=0.5) -> bool` — True if every neighbor's metric is within `tol` (relative) of the center cell, i.e. no knife-edge. `surface: dict[tuple, float]` keyed by `(sma_window, atr_multiplier)`.
  - `build_plateau_surface(ticker="BTC-USD") -> dict[tuple, float]` — Calmar for each `(sma_window, atr_multiplier)` in the neighborhood grid `sma_window ∈ {150,200,250}`, `atr_multiplier ∈ {2.0,2.5,3.0}` (±~25%/±20% of inherited).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_btc_trend_screen.py
from backtest.btc_trend_screen import plateau_ok


def test_plateau_ok_true_when_neighbors_close():
    surface = {(150, 2.0): 0.9, (200, 2.5): 1.0, (250, 3.0): 1.1,
               (200, 2.0): 0.95, (200, 3.0): 1.05, (150, 2.5): 0.92,
               (250, 2.5): 1.08, (150, 3.0): 0.9, (250, 2.0): 1.0}
    assert plateau_ok(surface, (200, 2.5), tol=0.5) is True


def test_plateau_ok_false_on_knife_edge_spike():
    # center is a lonely spike; neighbors are far below (relative gap > tol)
    surface = {(200, 2.5): 2.0, (150, 2.5): 0.2, (250, 2.5): 0.2,
               (200, 2.0): 0.2, (200, 3.0): 0.2}
    assert plateau_ok(surface, (200, 2.5), tol=0.5) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_btc_trend_screen.py -k plateau -v`
Expected: FAIL with `ImportError: cannot import name 'plateau_ok'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backtest/btc_trend_screen.py
PLATEAU_SMA = [150, 200, 250]
PLATEAU_ATR = [2.0, 2.5, 3.0]


def plateau_ok(surface, center_key, metric="calmar", tol=0.5):
    """True if no neighbor's value deviates from the center by more than `tol`
    (relative). A knife-edge spike (center >> neighbors) returns False."""
    center = surface.get(center_key)
    if center is None or not np.isfinite(center) or center == 0:
        return False
    for key, val in surface.items():
        if key == center_key or not np.isfinite(val):
            continue
        if abs(val - center) / abs(center) > tol:
            return False
    return True


def build_plateau_surface(ticker="BTC-USD"):
    surface = {}
    for sma in PLATEAU_SMA:
        for atr in PLATEAU_ATR:
            k = run_config(SMATrendFollowing(sma_window=sma, atr_multiplier=atr), ticker)
            surface[(sma, atr)] = k["calmar"] if k else float("nan")
    return surface
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_btc_trend_screen.py -k plateau -v`
Expected: PASS.

- [ ] **Step 5: Wire the surface into `main()` and print it**

Add to `main()` after the cycle table (before writing `doc`):

```python
    surface = build_plateau_surface()
    center = surface.get((200, 2.5), float("nan"))
    is_plateau = plateau_ok(surface, (200, 2.5))
    surf_lines = "| SMA \\ ATR | 2.0 | 2.5 | 3.0 |\n| :--- | ---: | ---: | ---: |\n"
    for sma in PLATEAU_SMA:
        cells = " | ".join(f"{surface[(sma, atr)]:.2f}" for atr in PLATEAU_ATR)
        surf_lines += f"| {sma} | {cells} |\n"
    surf_note = (f"\n> Center (200/2.5) Calmar = {center:.2f}; "
                 f"plateau_ok = **{is_plateau}** (neighbors within ±50% of center). "
                 f"Robustness check only — NOT used to pick BTC params.\n")
```

And extend the `doc` string with a `## Parameter plateau (Calmar)` section containing `surf_lines + surf_note`.

- [ ] **Step 6: Run the screen and the tests**

Run: `python backtest/btc_trend_screen.py` then `python -m pytest tests/test_btc_trend_screen.py -v`
Expected: screen prints a 3×3 plateau table + plateau_ok verdict; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backtest/btc_trend_screen.py tests/test_btc_trend_screen.py
git commit -m "feat(btc): parameter-plateau robustness surface"
```

---

### Task 6: Cross-asset replication (ETH, LTC — untuned)

Run the same two untuned configs on ETH-USD and LTC-USD as semi-independent corroboration. Append a replication table to the output.

**Files:**
- Modify: `backtest/btc_trend_screen.py`

**Interfaces:**
- Consumes: `run_config`, `CONFIGS`.
- Produces: `build_replication_table(tickers=("ETH-USD", "LTC-USD")) -> str` — for each ticker, buy-&-hold vs core vs core+stop CAGR and Worst DD.

- [ ] **Step 1: Implement** (formatting glue over tested `run_config`; validated by running)

```python
# append to backtest/btc_trend_screen.py
REPLICATION_TICKERS = ("ETH-USD", "LTC-USD")


def build_replication_table(tickers=REPLICATION_TICKERS):
    head = ("| Asset | Config | CAGR | Worst DD | Calmar |\n"
            "| :--- | :--- | ---: | ---: | ---: |\n")
    body = ""
    for t in tickers:
        for name, factory in CONFIGS:
            k = run_config(factory(), t)
            if k is None:
                body += f"| {t} | {name} | — | — | — |\n"
                continue
            body += (f"| {t} | {name} | {k['cagr']*100:.2f}% | "
                     f"{k['max_dd']*100:.2f}% | {k['calmar']:.2f} |\n")
    return head + body
```

Wire into `main()`: build the replication table and add a `## Cross-asset replication (untuned)` section to `doc`, with a note that ETH/LTC are 0.7–0.8 correlated to BTC (only semi-independent).

- [ ] **Step 2: Run the screen end-to-end**

Run: `python backtest/btc_trend_screen.py`
Expected: replication table renders for ETH-USD and LTC-USD; DDs finite and plausible (crypto buy-&-hold DDs ≈ −85% to −95%).

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_btc_trend_screen.py -v`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add backtest/btc_trend_screen.py
git commit -m "feat(btc): untuned ETH/LTC cross-asset replication"
```

---

### Task 7: Writeup doc + verdict + README entry

Produce the strategy writeup with the pre-registered bar quoted verbatim (dated before results), the result tables, the `classify_verdict` output, and the honest caveats. Add the README "Explored and set aside" entry if the verdict is FAIL/INCONCLUSIVE.

**Files:**
- Create: `docs/strategies/btc-trend-following.md`
- Modify: `README.md` (the "Explored and set aside (negative results)" list, ~line 46-69) — only if verdict is FAIL/INCONCLUSIVE.

**Interfaces:**
- Consumes: the printed output of `backtest/btc_trend_screen.py` and the `classify_verdict` result.

- [ ] **Step 1: Run the screen and capture final numbers**

Run: `python backtest/btc_trend_screen.py`
Copy the headline table, per-cycle table, plateau table, and replication table from `backtest/btc_trend_screen_output.md`.

- [ ] **Step 2: Compute the verdict for each config**

Run (fill the dd_reduction list from the per-cycle table's Core+Stop column, cagr give-up from headline, calmars from headline, plateau from the plateau section):

```bash
python -c "from backtest.btc_trend_screen import classify_verdict; print(classify_verdict([<c1_pp>, <c2_pp>, <c3_pp>], <cagr_giveup_frac>, <calmar_strat>, <calmar_bh>, <plateau_bool>))"
```

- [ ] **Step 3: Write `docs/strategies/btc-trend-following.md`**

Structure (fill with actual numbers — NO placeholders in the committed doc):
- **Header** linking back to README, dated 2026-08-21.
- **Goal & the history problem** — restate: feasibility study, "inconclusive" is valid; ~2.5 in-sample cycles; why no rolling windows.
- **Pre-registered bar** — quote spec §5 verbatim, with a line stating it was fixed before results.
- **Results** — the four tables from the screen.
- **Verdict** — the `classify_verdict` output per config, with one paragraph of interpretation.
- **Caveats** — N≈2.5, semi-independent replication (0.7–0.8 corr), regime concentration (one repeated archetype), yfinance data quality, 2014-15 partial.

- [ ] **Step 4: If verdict is FAIL/INCONCLUSIVE, add a README entry**

Add a bullet to the "Explored and set aside (negative results)" list (README.md ~line 52-66) in the existing style:

```markdown
- **Bitcoin trend-following** (spot BTC, untuned equity rule) — [verdict]. The
  SMA200+ATR rule was applied unchanged to spot BTC over 2014–2026; with only
  ~2.5 in-sample drawdown cycles the result [transfers / does not transfer /
  cannot be separated from luck]. See
  [btc-trend-following](docs/strategies/btc-trend-following.md).
```

If verdict is PASS, do NOT add a negative entry; instead note in the doc that promotion to a production sleeve is a separate follow-on cycle (out of scope here).

- [ ] **Step 5: Commit**

```bash
git add docs/strategies/btc-trend-following.md README.md backtest/btc_trend_screen_output.md
git commit -m "docs(btc): feasibility writeup + verdict + README entry"
```

---

## Self-Review

**Spec coverage:**
- §2 credibility levers → out-of-sample-by-construction (Global Constraints: no tuning), pre-registration (Task 2 verdict + Task 7 quote), per-cycle disaggregation (Task 1 + Task 4), cross-asset replication (Task 6), plateau surface (Task 5), bootstrap (spec marked "only if time permits" — intentionally omitted from the plan as optional; noted here as a known deferral). ✓
- §3 data (BTC-USD 2014, cycles, ETH/LTC) → Tasks 3, 1, 6. ✓
- §4 two untuned configs, no dual-signal → Task 3 `CONFIGS`. ✓
- §5 pass/fail bar → Task 2 `classify_verdict`. ✓
- §6 benchmark + metrics + per-cycle table → Tasks 3, 4. ✓
- §7 deliverables (screen, doc, README) → Tasks 3-7. ✓
- §8 testing (network-free units, reconstruction sanity) → Tasks 1-5 tests, Task 3 Step 4 live check. ✓
- §9 caveats → Task 7 Step 3. ✓

**Deferred by design:** block bootstrap (§2 item 6) — spec explicitly makes it optional ("only if time permits"); excluded to keep the plan focused. Flagged for the reviewer, not a silent drop.

**Placeholder scan:** The only intentional fill-in-the-blanks are in Task 7 (actual result numbers that don't exist until the screen runs) — these are data outputs, not code placeholders, and the step instructions say NO placeholders survive into the committed doc. All code steps contain complete implementations. ✓

**Type consistency:** `run_config` returns a KPI dict including `equity_curve` (used by `cycle_max_drawdown` in Task 4 and consumed by `build_cycle_table`); `_kpis` keys (`cagr`, `max_dd`, `calmar`, `sharpe`, `trades`, `equity_curve`) match every consumer. `classify_verdict` signature is identical in Task 2 definition and Task 7 usage. `plateau_ok(surface, center_key, ...)` signature consistent. `CONFIGS` names match between `run_config` callers and the table builders. ✓
