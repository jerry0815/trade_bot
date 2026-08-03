# Overlay Comparison: Trailing Stop vs. VIX-Adaptive vs. Baseline (2026-08-03)

## Method

`backtest/overlay_comparison_rolling.py` runs baseline plus both
experimental `SMATrendFollowing` overlays — the trailing stop and the
`vix_threshold` T+2 bypass — on this project's standing 172-window rolling
methodology (pre-tax, `^NDX`/3x, S&P signal, SMA 200 / ATR x2.5 / T+2).

This is the first time `vix_threshold` has been through the rolling
aggregate at all. It was explored in the 2026-08-01 session
(`docs/session-handover-2026-08-01.md` Phase 5) via event-relative decline
and a single full-history run, then shelved. All three thresholds from that
exploration (25/30/35) are run here, to test parameter stability the same
way the trailing-stop grid was tested.

**Reproduction check passed.** The COVID segmentation for `VIX>30` returns
+3.04pp on COVID-containing windows and +0.11pp on the rest — matching the
handover's recorded figures exactly, confirming this script reproduces the
prior finding rather than computing something different.

## Aggregate Result

| Config | Avg TWR | vs. baseline | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 21.77% | — | 22.13% | 8.31% | -83.40% | 11.1 |
| stop 8%, 60d | 23.43% | +1.66pp | 23.92% | 12.30% | **-64.78%** | 17.8 |
| stop 10%, 40d | 25.54% | +3.77pp | 25.87% | 12.17% | -86.20% | 13.6 |
| stop 12%, 20d | 24.80% | +3.03pp | 24.79% | 11.71% | -83.40% | 12.1 |
| VIX>25 | 23.21% | +1.44pp | 23.50% | 11.68% | -83.40% | 11.1 |
| VIX>30 | 23.22% | +1.45pp | 23.41% | 12.26% | -83.40% | 11.1 |
| VIX>35 | 22.35% | +0.58pp | 22.74% | 10.66% | -83.40% | 11.1 |

On **return alone**, `VIX>30` (+1.45pp) and `stop 8%, 60d` (+1.66pp) are
near-equivalent, and `VIX>30` achieves it with **no added trading**
(11.1 trades, identical to baseline — the bypass changes *when* a trade
fires, not *how many* fire). That is a genuine advantage: no added
commission or short-term-tax exposure.

## Drawdown

| Config | Windows improved | Worsened | Identical | Mean Max DD |
| :--- | ---: | ---: | ---: | ---: |
| baseline | — | — | — | -83.13% |
| stop 8%, 60d | **172** | **0** | 0 | **-64.77%** |
| stop 10%, 40d | 4 | 168 | 0 | -85.66% |
| stop 12%, 20d | 60 | 60 | 52 | -82.91% |
| VIX>25 | 66 | 55 | 51 | -82.91% |
| VIX>30 | 56 | 54 | 62 | -82.91% |
| VIX>35 | 56 | 54 | 62 | -82.91% |

**VIX-adaptive provides no drawdown benefit whatsoever.** All three
thresholds leave Worst DD at exactly baseline's -83.40%, mean Max DD within
0.22pp of baseline, and per-window results are a coin flip. `stop 8%, 60d`
remains the only configuration tested that reduces drawdown, and it does so
in every window without exception.

**A caution about single-window evidence.** On the held-out 2016-today
window (`docs/trailing-stop-loss-out-of-sample-2026-08-02.md`), `VIX>30`
showed Max DD -61.50% against baseline's -72.26% — an apparent 10.76pp
drawdown improvement. Across 172 windows that effect is zero. This is the
same trap that produced the erroneous `(10%, 40d)` recommendation corrected
in `docs/trailing-stop-loss-region-validation-2026-08-03.md`: a single
10-year window with ~5 trades is not sufficient evidence about drawdown
behavior, in either direction.

## COVID Concentration

Baseline Avg TWR: 20.07% on COVID-containing windows (start ≥ 1994, N=79)
vs. 23.21% on the rest (N=93).

| Config | COVID-window improvement | Non-COVID improvement | Gap |
| :--- | ---: | ---: | ---: |
| stop 8%, 60d | +2.18pp | +1.22pp | +0.96pp |
| stop 10%, 40d | +4.59pp | +3.08pp | +1.52pp |
| stop 12%, 20d | +4.06pp | +2.15pp | +1.90pp |
| VIX>25 | +2.63pp | +0.44pp | +2.19pp |
| VIX>30 | +3.04pp | +0.11pp | +2.93pp |
| VIX>35 | +2.12pp | **-0.72pp** | +2.84pp |

The handover's skeptical read of `vix_threshold` is confirmed on the full
aggregate: essentially all of its benefit lives in windows containing
COVID. Outside those windows it contributes +0.44pp, +0.11pp, and **-0.72pp**
at the three thresholds — nothing, or a net drag. Its apparent aggregate
improvement is one event, diluted across 79 of 172 windows.

The trailing stop's benefit is far more evenly distributed: `stop 8%, 60d`
improves non-COVID windows by +1.22pp, roughly 56% of its COVID-window
improvement. It is helped by COVID, but does not depend on it.

## Verdict

Comparing the two overlays directly:

- **On return**, they are close (`VIX>30` +1.45pp vs. `stop 8%, 60d`
  +1.66pp), and VIX-adaptive wins on cost — zero added trades against the
  stop's 60% turnover increase.
- **On drawdown**, it is not close. The stop improves 172/172 windows
  (-83.13% → -64.77% mean); VIX-adaptive does nothing.
- **On robustness**, the stop wins. VIX-adaptive's return benefit is ~96%
  COVID-concentrated (+3.04pp vs. +0.11pp at the best threshold) and turns
  negative outside COVID at `VIX>35`. The stop's is distributed across both
  segments.

`vix_threshold` should stay shelved. Its one measured advantage — free
return improvement with no added trading — rests almost entirely on a
single event recurring, which is the same reason it was shelved in the
first place; the rolling aggregate confirms rather than overturns that call.

This leaves the conclusion from
`docs/trailing-stop-loss-region-validation-2026-08-03.md` unchanged: if any
overlay is adopted, it is `(8%, 60d)`, adopted for drawdown reduction, with
its return contribution treated as roughly a wash after realistic costs.
Nothing tested here provides a reason to prefer VIX-adaptive over it, or to
run both.
