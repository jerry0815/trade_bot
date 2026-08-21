# Design — Dynamic-Leverage 3-Gear

**Date:** 2026-08-21
**Status:** design approved, spec under review
**Author:** Claude Code (with Jerry)
**Related:** [research-retrospective-2026-08.md](../../research-retrospective-2026-08.md) · [core-trend-signal.md](../../strategies/core-trend-signal.md) · [strat_backtest.py](../../../backtest/strat_backtest.py)

---

## 1. Motivation

The production rule is **binary**: 3× TQQQ when both indices trend bullish, else 0× (cash/SGOV).
The repo's own conclusion is that the *only* lever that meaningfully moves the deep
(−50% to −65%) worst-case drawdowns is **leverage itself** — 2× roughly halves the worst case
for a modest return give-up — not a smarter signal. Two adjacent ideas were already tested and
set aside: an options overlay (negative — wrong payoff sign for a long-convex trend-follower)
and volatility-targeted sizing (neutral — redundant with the cash rotation).

This project tests the one leverage idea the binary rule leaves on the table: a **middle gear**.
The binary rule handles the ambiguous zone near the SMA bluntly ("hold whatever you had").
A three-gear rule instead assigns that zone a *defined, reduced* leverage — de-risking into
the transition rather than staying fully levered until the signal finally flips. The thesis:
attack the drawdown at the **entry/exit boundary**, a different mechanism than vol-targeting,
so the "redundant with cash rotation" objection does not automatically apply.

**Burden of proof is on this idea.** The baseline is well-tuned; "nothing beat it" is the
prior. This spec is designed to produce a *clean negative* if the middle gear doesn't help.

## 2. The rule — reuse existing dual-signal states

No new thresholds. Map the existing dual-signal state machine's three states directly to
leverage levels:

| Gear | Condition (existing signals, unchanged) | Exposure |
|---|---|---|
| **Full** | ^NDX **and** ^GSPC both bullish (`Close > SMA200 + 2.5·ATR`) | **3×** |
| **Reduced** | mixed — one bullish, one not (today's "hold" zone) | **middle gear (swept)** |
| **Cash** | both bearish (`Close < SMA200 − 2.5·ATR`) | **0× (SGOV)** |

The **only** new behavior: the ambiguous zone that the production rule currently resolves as
stateful hysteresis ("hold prior position") becomes a **fixed reduced-leverage sleeve**. This
deliberately removes the hysteresis in that zone — that trade-off is the thing under test, and
it will be reported explicitly (turnover / rebalance count vs the binary rule).

**Middle-gear level is swept, not guessed:** test the reduced gear at **{1×, 1.5×, 2×}**.
1× and 2× bracket the interesting range; if none of the three beats the baselines, that is a
clean, defensible negative.

## 3. Engine change — per-day exposure vector

Today `Backtester.leverage` is a **scalar** applied uniformly, and the daily-return array is
built with three vectorised cases — entry (open→close), hold (close→close), exit (overnight
gap) — each at that one scalar leverage ([strat_backtest.py:978-991](../../../backtest/strat_backtest.py)).

**Change:** let a strategy emit a per-day `target_leverage` column (float, 0 ≤ L ≤ 3).
The engine consumes it as follows, **generalising the existing three cases and adding exactly
one new one**, so the current behavior is preserved bit-for-bit when `target_leverage` is
absent or constant:

Let `old_L[t] = target_leverage[t-1]` and `new_L[t] = target_leverage[t]` (both lookahead-free:
`new_L[t]` is decided from `t-1` close signals and acted at `t`'s open, exactly as `in_market`
is today).

| Day type | old_L, new_L | Daily return | Status |
|---|---|---|---|
| Hold | old==new>0 | `ret_1x·L − drag(L)` | unchanged |
| Entry (from cash) | old==0, new>0 | `o2c·new_L − drag(new_L)` | unchanged (matches today's entry) |
| Exit (to cash) | old>0, new==0 | `ovn·old_L − drag(old_L)` | unchanged (matches today's exit) |
| **Gear change** | old>0, new>0, old≠new | `ovn·old_L + o2c·new_L − drag(new_L)` | **NEW** |

`drag(L) = ((L−1)·BR + expense_ratio)/252`, evaluated per-day at that day's leverage.
On cash days (L==0): the existing `cash_ret = BR·0.8/252`.

The gear-change formula is the *rigorous* model of a next-day-open rebalance (hold the overnight
gap at the old exposure, the intraday move at the new exposure) and it reduces exactly to the
entry and exit rows when one side is 0 — so all four cases are one consistent rule. Gear changes
are infrequent (regime transitions only), so this is not a hot path.

**Backward-compatibility contract:** when a strategy does not emit `target_leverage`, the engine
falls back to `scalar leverage × in_market` and every existing result is unchanged. This is a
required test.

## 4. The strategy object

New strategy class (e.g. `DynamicLeverageTrend`) that **reuses the existing dual-signal state
computation** and emits both `in_market` (= `target_leverage > 0`, for trade/cash stats) and
`target_leverage`. It takes `middle_gear` as a parameter so the sweep is one object,
three configs. No new indicator code — it consumes the same SMA200/ATR/dual-signal columns.

`_calculate_trade_stats` keeps counting **entries from cash** as "trades" (via `in_market`).
Gear changes (3×↔middle) are reported *separately* as "rebalances" so the added turnover of the
middle gear is visible and honestly costed, not hidden.

## 5. What it must beat

Not just the incumbent — the honest competitor set:

1. **Binary 3×-or-cash** (the production sleeve) — the incumbent.
2. **Fixed 2× TQQQ** (same signal) — the cheap alternative that *already* halves the worst
   drawdown with zero added machinery. This is the real bar: dynamic leverage has to beat
   "just permanently run 2×," not merely beat 3×.

**Success = a risk-adjusted win:** Calmar and/or Sharpe materially above *both* baselines —
not merely sliding to a different point on the same return/risk line (which fixed 2× already
offers for free). Reported metrics: CAGR, worst drawdown (both peak-to-trough and vs-initial),
Calmar, Sharpe, trades, rebalances.

## 6. Validation — staged, single-path is a screen not a verdict

The repo has twice been burned by single-path / frictionless inflation. So:

1. **Screen (cheap):** single continuous **1990–2026** path, on the **single-signal sleeve
   first** to isolate the mechanism cleanly. Compare all three middle gears vs both baselines.
   A screen result is a *go/no-go for deeper work*, never a headline.
2. **Confirm (only if the screen shows a real edge):** the repo's gold standard — the
   **rolling-window** engine (26-year windows, monthly step) + the **reconstruction** dataset
   for the four-bear stress test, on the **production dual-signal + trailing-stop sleeve**.
   Cross-check the crash windows (dot-com, 2008, COVID, 2022) the way the trailing-stop and
   options work did.

If the screen is negative across all three gears, the project ends there with a documented
negative finding folded into the retrospective — no rolling run needed.

## 7. Realism caveats (to state alongside any result)

- Fractional leverage (1.5×) is an **idealization** — in practice a TQQQ+cash blend, or QQQ on
  margin. Same abstraction the existing 1×/2×/3× tiers already use; the drag formula generalizes
  it, but real rebalancing friction, tracking error, and the expense/borrow split at fractional
  exposure are not separately modeled.
- `expense_ratio` is applied as-is when in-market; it is not scaled by the TQQQ fraction of a
  blended position. Minor, and conservative-ish; noted, not modeled.
- All screen results are single-path and frictionless — magnitudes approximate; only the
  *ranking* vs baselines is load-bearing, and only after the confirm stage.

## 8. Testing (TDD)

Unit tests before implementation, mirroring the repo's existing `tests/` style (synthetic /
pure-math, no network):

- **Backward-compat:** a `target_leverage`-free strategy reproduces the current scalar-leverage
  results exactly (regression guard on the engine change).
- **Constant-vector equivalence:** `target_leverage ≡ 3` everywhere reproduces the scalar-3×
  result day-for-day.
- **Case coverage:** hand-built exposure vectors exercising each of the four day types
  (hold / entry / exit / gear-change), asserting the daily-return formula per row — especially
  the new gear-change row (overnight at old L, intraday at new L).
- **No-lookahead:** `target_leverage[t]` depends only on data through `t−1`.
- **Strategy mapping:** the three dual-signal states map to `{3×, middle, 0×}` correctly, and
  `in_market == (target_leverage > 0)`.

## 9. Out of scope

- Continuous / trend-strength-bucketed leverage (explicitly deferred — discrete 3-gear chosen
  to minimize overfit surface; revisit only if 3-gear shows a real edge).
- LEAPS-as-leverage (a separate options thread; parked).
- Any change to the production `bot.py` recommendation. This is research on a branch; adoption
  is a later, separate decision gated on the confirm-stage result.
- Options overlay in any form (closed; see retrospective).

## 10. Deliverables

- Engine change + `DynamicLeverageTrend` strategy + unit tests (all green).
- A screen script (`backtest/dynamic_leverage_screen.py`) producing the 1990–2026 comparison table.
- A findings doc — folded into the retrospective if negative; its own strategy doc + README row
  if the confirm stage produces a genuine, robust win.
