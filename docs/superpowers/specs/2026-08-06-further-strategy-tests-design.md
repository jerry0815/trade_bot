# Design: Three Further Strategy Tests (velocity stop, QQQ 1x, taxable account)

**Date:** 2026-08-06
**Status:** Approved (design), pending implementation plan

## Motivation

Three follow-up tests requested on top of the existing signal-hybrid + trailing-stop
research (README Tables 4–5):

1. A **fixed-window ("velocity") trailing stop** — trigger on an 8%-ish drop that
   happens *within N days*, as an alternative to the current peak-based stop (8%
   below the running peak since entry).
2. The **current live strategy run on QQQ** (unleveraged NASDAQ-100, 1x).
3. A **taxable-account** view of the key setups (after-tax returns).

### Key framing (from brainstorming)

The two stop types measure different things:

| Stop | Measures | Catches | Blind spot |
| :--- | :--- | :--- | :--- |
| Peak-based (current, 8%/60d) | *Magnitude* — distance below running high | Any ≥8% decline off the peak, fast or slow | Whipsaws on ordinary 8–10% corrections → more trades |
| Velocity (fixed-window) | *Speed* — drop over a bounded window | Fast crashes (COVID, Black Monday) | A slow-grinding bear that never loses 8% in one window (dot-com, 2022) |

README Table 5 already shows the peak-based stop is the largest drawdown reducer in
**all five** crashes, including the slow ones (dot-com −83%→−51%, 2022 −52%→−38%).
So the velocity stop's *value proposition* is **fewer whipsaws**, and its *risk* is
**missing slow bears**. The goal of these tests is to measure that trade-off with the
project's own data through the two lenses already in use:

- **Table 4 lens** (rolling TWR / drawdown / trade count) → does the velocity stop cut whipsaws?
- **Table 5 lens** (per-crash event-relative decline) → does it still catch slow bears?

## Scope

Three standalone scripts under `backtest/`, following existing conventions (print a
markdown table to stdout **and** write it to a sibling `_output.md`), plus README
tables and `docs/` finding notes. One engine change (the new stop mechanism).

Out of scope: commission/slippage modeling (a pre-existing, separately-tracked gap);
changing `bot.py`'s live config (the velocity stop is added as a testable option, not
promoted, unless a later decision says so).

---

## Part 1 — Velocity (fixed-window) trailing stop

### Mechanism

A stop that triggers on the *speed* of a decline. Two interpretations, both
**lookahead-free** — every read decides on `close[i-1]` and earlier, matching the
existing `_apply_trailing_stop` (in_market[i] is the execution-day column; an exit
sells at day i's open, so day i's decision may only use info before that open):

- **rolling-max:** exit when `close[i-1] < (max of close over the trailing `window`
  days ending at i-1) * (1 - pct)`.
- **point-to-point:** exit when `close[i-1] < close[i-1-window] * (1 - pct)`.

After a stop-triggered exit, block re-entry for `cooldown` trading days (same as the
peak stop). Precedence matches the existing stop: a trend-signal exit wins over a
stop breach on the same day and does **not** start a cooldown; only a stop-triggered
exit does. The window is measured over the trailing price series regardless of entry
date (a market-velocity measure); it only *applies* while in a position.

Tracks `^GSPC` (unleveraged) — same reference price as the peak stop, passed via the
existing `price=` argument path (`DualSignalAgreement` supplies `^GSPC` explicitly;
the S&P-signal `SMATrendFollowing` already has `df['Close'] == ^GSPC`).

### Implementation (chosen: Option A)

Add `BaseStrategy._apply_velocity_stop(df, price=None)`, parallel to
`_apply_trailing_stop`, driven by new strategy params:

- `velocity_stop_pct` (None disables — mirrors `trailing_stop_pct`)
- `velocity_stop_window` (trailing lookback in trading days)
- `velocity_stop_mode` ∈ {`"rolling_max"`, `"point_to_point"`}
- `velocity_stop_cooldown_days`

Wire into `SMATrendFollowing._add_indicator_logic` and
`DualSignalAgreement._add_indicator_logic` the same way the peak stop is wired
(after the vectorized state machine; sequential by nature). The peak stop's
`_apply_trailing_stop` output is a regression gate per the existing code comments and
**must stay byte-for-byte unchanged** — the velocity stop is a separate method and a
separate set of params; the two are mutually exclusive per run (a strategy sets one
or the other, not both).

Rejected alternatives: (B) generalizing `_apply_trailing_stop` with a `peak_window`
param — point-to-point isn't a peak, and it risks perturbing the regression gate;
(C) computing the stop only inside the sweep script — duplicates the careful
lookahead-free logic and can never go live.

### Sweep (`backtest/velocity_stop_sweep.py`)

Selection phase (fast, single-run event-relative decline like
`trailing_stop_sweep.py`) over the grid, on the two live-relevant setups
(S&P-signal[T+2] and dual-signal agreement, ^NDX base / 3x / ATR 2.5):

- mode ∈ {rolling_max, point_to_point}
- window ∈ {20, 30, 60} days
- pct ∈ {6, 8, 10, 12}%
- cooldown ∈ {20, 40, 60} days

= 72 variants. Reports each variant's per-crash decline vs the no-stop baseline, so
the slow-bear blind spot (dot-com, 2022) is directly visible.

Evaluation phase: run only the **chosen** velocity variant(s) through the **full
rolling** Table-4 comparison (Avg/Med/Worst TWR, Worst DD, Avg Trades) alongside the
existing peak-8%/60d stop and the no-stop setups, and add them to the per-crash
Table-5 comparison.

### Crash table (`backtest/crash_event_drawdown.py`)

Extend with rows for the chosen velocity variant(s), so Table 5 shows peak-based vs
velocity side by side across the five crashes.

### Tests

Unit tests for `_apply_velocity_stop` on hand-built price series:
- rolling-max triggers on a fast drop, holds through a slow drop that stays within pct/window;
- point-to-point triggers only on the window-spaced comparison;
- cooldown blocks re-entry for exactly `cooldown` days;
- trend-exit precedence (no cooldown started);
- lookahead-freeness (decision uses only `close[i-1]` and earlier).

---

## Part 2 — QQQ full strategy sweep at 1x (`backtest/qqq_strategy_sweep.py`)

Every Table-4 setup (NDX-own, S&P-signal, dual-signal; ±T+2; ± the chosen/peak
stop) at **leverage=1** with QQQ's **0.20% expense ratio**, rolling windows, plus
Buy & Hold. Uses the same `^NDX` data the engine already models at 1x — QQQ *is* 1x
NASDAQ-100 — with the ETF's real expense drag. Output: a new README table,
"QQQ (1x) — Strategy Comparison."

---

## Part 3 — Taxable-account table (`backtest/taxable_account_comparison.py`)

The key setups (single-signal[T+2], dual-signal, and their stopped variants; 3x
^NDX) run with `apply_tax=True` (engine defaults: 25% on gains held ≤365 days, 15%
otherwise). Reports **pre-tax TWR, after-tax TWR, tax drag (pp), after-tax max
drawdown, total tax paid**, reusing the rendering pattern in
`trailing_stop_tax_aware_out_of_sample.py`. Because the stop roughly doubles trades
and forces short-term gains, this quantifies where tax drag bites hardest. Output: a
new README table, "Taxable Account — After-Tax Comparison."

---

## Deliverables / files touched

- **`backtest/strat_backtest.py`** — new `_apply_velocity_stop` + new params on
  `SMATrendFollowing` and `DualSignalAgreement`.
- **New:** `backtest/velocity_stop_sweep.py`, `backtest/qqq_strategy_sweep.py`,
  `backtest/taxable_account_comparison.py` (+ their `_output.md`).
- **`backtest/crash_event_drawdown.py`** — chosen velocity variant(s) added.
- **Tests** for `_apply_velocity_stop`.
- **`README.md`** — Tables 6–8 with interpretive notes and caveats in the existing voice.
- **`docs/`** — a finding note per result, in the `docs/trailing-stop-*` chain style.

## Caveats to carry into the write-ups

- Overlapping-window caveat (monthly-stepped rolling windows share most history).
- Single-run selection sweep is not itself stability/OOS-validated (mirrors the
  Table 4 caveat).
- Velocity stop is new code; validate by hand-tracing + unit tests before publishing
  numbers, same bar as `DualSignalAgreement`.
- QQQ actual ETF inception is 1999; the 1x sweep uses `^NDX` (index) data with QQQ's
  expense ratio, not QQQ's own price history — note this explicitly.
