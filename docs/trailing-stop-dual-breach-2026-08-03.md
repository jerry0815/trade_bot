# "Both Must Breach" Dual Trailing Stop (2026-08-03)

## The idea tested

Mirror the dual-signal *entry* rule on the *exit*: hold the position until
**both** ^NDX and ^GSPC have each independently breached their own trailing
stop (each fallen `pct` below its own peak-since-entry). Exit only on that
joint breach. Prior tests fired on a single ticker's breach; this requires
agreement.

`backtest/trailing_stop_dual_breach.py`, 172-window rolling aggregate,
^NDX/3x, pre-tax. New `_apply_dual_trailing_stop` overlay written in the
script (no engine change), mirroring the tested single-ticker loop exactly
— same one-day lag, same fresh-entry peak seeding, same trend-exit-wins
precedence, same cooldown — but tracking two peaks and requiring both
breached.

## Result

Dual-signal baseline (no stop): Avg TWR 25.81%, mean Max DD -84.59%, 8.8 trades.

| Config | Avg TWR | vs. base | Worst DD | DD improved | Mean Max DD | Trades |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 6%, 60d | 16.36% | -9.45pp | -69.04% | 172/172 | -68.65% | 27.4 |
| 7%, 60d | 16.56% | -9.25pp | -67.55% | 172/172 | -67.55% | 22.8 |
| **8%, 60d** | 19.13% | -6.68pp | -89.46% | **4/172** | **-88.87%** | 17.9 |
| 9%, 60d | 17.80% | -8.00pp | -89.46% | 4/172 | -88.87% | 16.7 |
| 10%, 60d | 23.57% | -2.24pp | -89.46% | 4/172 | -88.87% | 12.6 |

**The candidate width (8%) lands on the wrong side of a cliff and makes
drawdown WORSE.** At 8% and above, the joint-breach condition improves
drawdown in only 4 of 172 windows and *worsens* mean Max DD to -88.87%
(vs. baseline -84.59%). The cliff for this exit rule sits between 7% and 8%
— not between 9% and 10% as it did for the single-ticker stops.

Verified this is real, not an artifact: the 8/9/10% drawdown columns are
distinct arrays (14-15 unique values each), but their means converge
because at these widths the stop almost never fires early enough to catch
each window's *worst* drawdown episode — so max drawdown is set by the
un-stopped crash regardless of width. The only 4 windows where it helps are
all mid-2000 dot-com-top starts, the one scenario where both indices fell
8%+ from their peaks near-simultaneously and early.

## Exit-rule comparison at 8%, 60d (identical dual-signal entry)

| Exit rule | Avg TWR | vs. base | DD improved | Mean Max DD | Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| both must breach (NDX & GSPC) | 19.13% | -6.68pp | **4/172** | **-88.87%** | 17.9 |
| single: GSPC only | 24.59% | -1.22pp | 172/172 | -64.77% | 17.9 |
| single: NDX only | 14.24% | -11.57pp | 172/172 | -63.47% | 33.2 |

At the same width and same entry rule, the both-must-breach exit is
**strictly dominated by the single-GSPC exit**: identical turnover (17.9
trades), but it *worsens* drawdown where single-GSPC *improves* it
172/172, and it costs 5.46pp more return. Requiring agreement bought
nothing and lost the entire point of the stop.

## Why it backfires — the general lesson

Confirmation is the right instinct for an **entry** and the wrong one for a
protective **exit**.

- For an entry, requiring ^NDX and ^GSPC to agree filters false signals —
  which is exactly why the dual-signal baseline is a strong 25.81%
  strategy. You can afford to wait for confirmation before *buying*.
- For a stop, waiting for confirmation means waiting until *both* indices
  are already deep in the hole. By the time the slower of the two has
  fallen 8% from its own peak, the faster one is usually well past that,
  and the combined position is already near its worst — so the exit fires
  too late to protect anything, then the cooldown blocks the recovery. A
  protective stop should act on the **first** warning, not the confirmed
  one.

This is the same asymmetry the published stop already exploits by bypassing
T+2 confirmation on the exit: for getting *out*, speed beats certainty.

## Answer

The "both must breach" exit does not work as a drawdown tool — at the
candidate 8% width it actively worsens drawdown while still costing return,
and it is strictly dominated by simply tracking ^GSPC alone. It only helps
at very tight widths (6-7%), and even there it is worse on both axes than
the single-GSPC stop.

If a stop is added to the dual-signal strategy, it should be a
**single-ticker stop tracking ^GSPC**, firing on the first breach — not a
both-must-agree exit. Keep the agreement rule for the entry, where it
earns its keep; drop it for the exit, where it defeats the purpose.
