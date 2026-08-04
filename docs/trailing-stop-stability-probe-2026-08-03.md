# Trailing-Stop Parameter-Stability Probe (2026-08-03)

## Method

`backtest/trailing_stop_stability_probe.py` walks both parameter axes
around the `(8%, 60d)` candidate at finer resolution than the original
sweep grid, on the standard 172-window rolling set (pre-tax, `^NDX`/3x,
S&P signal).

**Why this was needed.**
`docs/trailing-stop-loss-region-validation-2026-08-03.md` found that
per-window drawdown behavior reverses sign between adjacent grid points:
`(8%, 60d)` improves drawdown in 172/172 windows, while the 10% configs
*worsen* it in 168/172. The original grid (5/7/8/10/12/15/20%) jumps
straight from 8% to 10%, so nothing had ever been measured in between. It
was therefore unknown whether 8% sat on a smooth plateau or on the edge of
a cliff — and a cliff is the same non-monotonic overfitting signature this
project has rejected three times before.

Probe: stop width 6/7/8/9/10% at fixed 60d cooldown, plus 8% at 40/60/80d.
`9%`, `6%`, and `80d` are new values never previously tested.

## Result

| Config | Axis | Avg TWR | vs. base | DD improved | DD worsened | Mean Max DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | — | 21.77% | — | — | — | -83.13% | 11.1 |
| 6%, 60d | pct | 15.93% | **-5.84pp** | 172 | 0 | -67.55% | 28.8 |
| 7%, 60d | pct | 14.35% | **-7.42pp** | 172 | 0 | -67.43% | 23.2 |
| **8%, 60d** | pct | 23.43% | +1.66pp | **172** | **0** | -64.77% | 17.8 |
| 9%, 60d | pct | 25.94% | +4.17pp | 172 | 0 | -63.06% | 16.7 |
| 10%, 60d | pct | 21.45% | -0.32pp | **4** | **168** | -87.78% | 13.6 |
| 8%, 40d | cooldown | 24.16% | +2.39pp | 172 | 0 | -68.19% | 18.8 |
| 8%, 80d | cooldown | 16.49% | **-5.28pp** | 172 | 0 | -69.19% | 17.8 |

The two claims attached to this mechanism come apart cleanly.

### The drawdown claim PASSES — decisively

Drawdown improves in **172 of 172 windows at every stop width from 6% to
9%**, and at every cooldown from 40d to 80d. Mean Max DD sits in a tight
-63% to -69% band across all seven configurations, against baseline's
-83.13%. This is a **plateau, not a point**: `(8%, 60d)` sits in the
interior of a four-point-wide region on the pct axis and the middle of the
tested cooldown range, with no sensitivity to either parameter.

The cliff is real but lives between **9% and 10%**, not adjacent to the
candidate — 172/172 collapses to 4/172 across that single step, with mean
Max DD flipping from -63.06% to -87.78% (worse than baseline). `(8%, 60d)`
has a full grid step of margin from it; `(9%, 60d)` does not.

The defensible claim is therefore mechanism-level, not point-level: **a
trailing stop set below 10% reliably reduces drawdown on this strategy**,
by roughly 15-20pp of mean max drawdown, regardless of where in the 6-9%
range it is set or what cooldown is used.

### The return claim FAILS — badly

Avg TWR across the same configurations swings from **-7.42pp to +4.17pp**
with no coherent gradient:

- 6% → 7% → 8% → 9% → 10% gives -5.84, **-7.42**, +1.66, **+4.17**, -0.32.
  Adjacent points differ by as much as 9.08pp (7% → 8%) and reverse sign
  twice.
- On the cooldown axis, 40d → 60d → 80d gives +2.39, +1.66, **-5.28** — a
  6.94pp collapse from a single step the original grid never tested.

The `+1.66pp` measured at `(8%, 60d)` is **not a stable property of the
mechanism**. It is one draw from a rough surface whose neighbors are
frequently and substantially negative. It should not be relied on, and the
earlier characterization of the return effect as "roughly a wash after
costs" was too generous — the honest estimate is *unknown, plausibly
negative*, with uncertainty of several percentage points in either
direction, before commissions and slippage are even modeled.

**Averaging the plateau gives a negative central estimate.** Picking the
best point on a noisy surface overstates it. Averaging instead across the
configurations that share the drawdown property:

- pct axis, 6/7/8/9% at 60d: -5.84, -7.42, +1.66, +4.17 → **mean -1.86pp**
- cooldown axis, 40/60/80d at 8%: +2.39, +1.66, -5.28 → **mean -0.41pp**

Both are negative. A grid is not a probability distribution over parameter
choices, so neither figure is a rigorous estimator — but both are more
defensible than the `+1.66pp` point estimate, which is the second-best of
four points on its own axis. The honest central estimate of the return
effect is a **cost of roughly 0.4-1.9pp/yr**, not zero and not a gain.

Note also that `(9%, 60d)` dominates the candidate on this data — better
return (+4.17pp vs. +1.66pp) *and* better drawdown (-63.06% vs. -64.77%).
It is not recommended over `(8%, 60d)` precisely because it sits directly
adjacent to the 10% cliff; preferring it would be selecting on exactly the
noisy return surface this section shows cannot be trusted.

## Verdict

This probe resolves the question it was built to answer, and splits the
finding in two:

- **Adopt-for-drawdown is now well-supported.** The 172/172 result is not a
  fitted artifact; it holds across a wide parameter plateau on both axes.
  This is the most robust result produced anywhere in this investigation.
- **Any return-based case is dead.** The return surface is noise at this
  resolution. No configuration should be selected, ranked, or justified on
  Avg TWR.

Restated as a single sentence: adopting `(8%, 60d)` buys a reliable ~18pp
reduction in mean maximum drawdown, at a return cost that is genuinely
unknown and could plausibly be several percentage points per year in
either direction, plus ~60% more trading whose commission and slippage
cost remains unmodeled.

Whether that trade is worth taking is a risk-tolerance judgment. The
backtests can now state the drawdown side of it with confidence; they
cannot state the return side at all.

## Remaining gaps

- ~~**Commissions and slippage are still unmodeled**~~ — **resolved
  2026-08-03**, and the concern was overstated. `backtest/trailing_stop_execution_cost.py`
  quantifies it: 6.7 extra round trips per 26-year window at a generous 2bps
  one-way assumption is 26.8bps total, or **0.0103pp/yr** — roughly three
  orders of magnitude below the ±5pp return-surface noise above. Commissions
  on US-listed ETFs are $0 at mainstream retail brokers. This was never the
  binding uncertainty; the parameter noise is.
- **Execution must be market-on-open, not a resting limit.** The same script
  measures the traded-ticker gap on all 25 historical stop-trigger days: the
  open is at or above the prior close 76% of the time, but gaps below it 24%
  of the time — and those 6 no-fill days cluster on the most severe events in
  the sample (2020-02-28 COVID at -3.59%, 2000-10-11 dot-com at -3.47%,
  2022-01-24 at -1.92%). A sell limit resting at the prior close fills on
  ordinary stop days and fails precisely during crashes, where it can remain
  unfilled for the entire decline. `Backtester._run_portfolio_math` already
  models the correct behavior (exit fills at today's open, gap included), so
  the backtested numbers are achievable — but only via an order type that
  participates in the opening auction.
- **The 9%/10% cliff mechanism is uninvestigated.** Why widening the stop
  by one point flips it from universally helpful to universally harmful is
  not understood. A plausible story (rarer firing lands the stop closer to
  bottoms, with the cooldown blocking the recovery) is untested speculation
  and is recorded here only as a hypothesis.
