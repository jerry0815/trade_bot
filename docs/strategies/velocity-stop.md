# Velocity (Fixed-Window) Stop

[← Back to README](../../README.md) · Related: [Methodology](methodology.md) · [Trailing Stop](trailing-stop.md)

An alternative crash filter to the peak-based [trailing stop](trailing-stop.md). The peak-based trailing stop exits when price falls a fixed pct below the running peak since entry. The velocity stop instead measures decline over a fixed trailing window rather than since-entry — testing whether a faster, window-bounded read catches sharp ("crazy") bears without over-reacting to slow ones.

- **`rolling_max`** — compares the latest close against the window's own max.
- **`point_to_point`** — compares the latest close against the close exactly `window` days earlier.

It is **not** used by `bot.py`; the peak-based trailing stop remains the shipped crash filter. This doc records why.

---

## Backtest Results

Rolling 26-year methodology per [Methodology](methodology.md).

### Table 6: Velocity (Fixed-Window) Stop vs. Peak-Based Stop
*^NDX base, 3x leverage, ^GSPC reference. The peak-based trailing stop ([Table 4](dual-signal-agreement.md)/[Table 5](trailing-stop.md)) exits when price falls a fixed pct below the running peak since entry. The velocity stop instead measures decline over a fixed trailing window instead of since-entry — `rolling_max` compares the latest close against the window's own max, `point_to_point` compares it against the close exactly `window` days earlier — testing whether a faster, window-bounded read catches sharp ("crazy") bears without over-reacting to slow ones. Winners selected from a 72-variant grid (mode x window x pct x cooldown) ranked by improvement over baseline event decline (`backtest/velocity_stop_sweep.py`): **rolling_max 6%/60d-window/60d-cooldown** and **point_to_point 6%/30d-window/60d-cooldown**.*

> **Crash-event lens ([Table 5](trailing-stop.md), rows E/F vs. D): the velocity stop does not leak on slow bears — the opposite of the a-priori hypothesis.** The worry going in was that a fixed-window stop, built to catch fast crashes, would fail to trigger on slower-grinding bears like dot-com (1999-2000) and 2022. It didn't: rolling_max (E) is dramatically better than the peak stop (D) on dot-com (-6.45% vs. -51.11%) and better on 2022 (-30.03% vs. -38.06%); point_to_point (F) also beats D on dot-com (-43.48% vs. -51.11%) and matches it exactly on 2022 (-38.06%). Both velocity variants match or beat the peak stop on all five crash events, not just these two.
>
> **Rolling-return lens (172-window aggregate below): the velocity stop underperforms the peak stop, and the trade-off is real, not free.** Avg TWR for the velocity variants clusters at 18.36%-21.58%, versus 24.59% for the peak stop and 25.81% for the dual-signal baseline with no stop at all — a return cost roughly 3-6x the peak stop's own (already-flat-to-negative) cost. It also trades *more* often (21-30 trades vs. the peak stop's 18, and dual-signal-no-stop's 9), not less — so the a-priori "does it whipsaw less" half of the question resolves **no**: the velocity stop does not reduce trading frequency; if anything it increases it.
>
> **Net read: the velocity stop is not a strictly better version of the peak stop — it is a more conservative one.** It buys equal-or-better crash protection at a real, larger compounding cost, with more trades along the way. Whether that trade is worth it depends on how much weight is put on tail protection during the specific slow-bear scenarios (dot-com, 2022) the peak stop already handles reasonably well.

| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Worst DD vs Init | Avg Trades | Windows |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dual-signal agreement (no stop) | **25.81%** | 26.68% | 11.68% | -84.95% | -84.95% | **9** | 172 |
| Dual-signal agreement + Trailing Stop 8%/60d (peak anchor) | 24.59% | 25.36% | 12.92% | -64.78% | -54.75% | 18 | 172 |
| S&P 500 signal [T+2] + Velocity Stop rolling_max 6%/60d, cooldown 60d | 18.36% | 18.83% | 11.06% | **-58.34%** | **-47.66%** | 30 | 172 |
| Dual-signal agreement + Velocity Stop rolling_max 6%/60d, cooldown 60d | 19.04% | 19.51% | 11.73% | -58.92% | **-47.52%** | 29 | 172 |
| S&P 500 signal [T+2] + Velocity Stop point_to_point 6%/30d, cooldown 60d | 21.58% | 22.40% | 12.87% | -67.52% | -53.46% | 21 | 172 |
| Dual-signal agreement + Velocity Stop point_to_point 6%/30d, cooldown 60d | 18.88% | 19.22% | 12.57% | -67.64% | -53.46% | 21 | 172 |

> **Caveats:** the rolling_max window (60d) is a tie-break artifact, not a meaningfully selected value — windows 20d/30d/60d produced *identical* event-decline results at 6%/60d-cooldown (see `backtest/velocity_stop_sweep_output.md`), because the rolling max over any of those windows was set by the same peak day in each test crash. Treat "60d" as "any of 20/30/60d gave the same answer here," not as evidence 60d is special. This is a single selection run, not checked for out-of-sample generalization or parameter stability the way the peak stop's [trailing-stop finding chain](trailing-stop.md#further-reading) was — same bar as the [Table 4 caveat](dual-signal-agreement.md). `_apply_velocity_stop` (`backtest/strat_backtest.py`) is new code, unit-tested and hand-traced for lookahead-freedom, but has not been through the multi-round adversarial review the core findings have. The usual overlapping-window caveat applies: 172 monthly-stepped windows share nearly all their history with their neighbors.

---

## Further reading

- [Velocity stop write-up (2026-08-06)](../velocity-stop-2026-08-06.md) — full analysis.
