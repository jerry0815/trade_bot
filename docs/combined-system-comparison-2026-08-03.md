# Combined System: Dual-Signal + Trailing Stop, In and Out of Sample (2026-08-03)

## Configs

| Cfg | Strategy |
| :-- | :--- |
| A | SMA 200 + T+2, S&P signal — the live `bot.py` baseline |
| B | A + GSPC trailing stop (8%, 60d) — the published stop |
| C | Dual-signal agreement, no T+2 — current README Table 4 pick |
| D | C + GSPC trailing stop (8%, 60d) — the combined system |

`backtest/combined_system_comparison.py`, ^NDX/3x, pre-tax. See script header
for the OOS-split honesty note (regime-change check, not a pristine hold-out).

## In-sample: 172-window rolling aggregate

| Cfg | Avg TWR | Med TWR | Worst DD | Mean Max DD | DD improved vs pair | Trades |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 21.77% | 22.13% | -83.40% | -83.13% | — | 11.1 |
| B | 23.43% | 23.92% | -64.78% | -64.77% | 172/172 (vs A) | 17.8 |
| C | 25.81% | 26.68% | -84.95% | -84.59% | — | 8.8 |
| D | 24.59% | 25.36% | -64.78% | -64.77% | 172/172 (vs C) | 17.9 |

## Out-of-sample: single backtest 2016-01-01 to today (10y)

| Cfg | TWR | Max DD | Trades |
| :-- | ---: | ---: | ---: |
| A | 19.20% | -72.26% | 4 |
| B | 22.50% | -48.73% | 8 |
| C | **33.12%** | -69.96% | 3 |
| D | 24.06% | **-48.73%** | 8 |

## Findings

### 1. Dual-signal's return edge survives out-of-sample — and grows

A vs C: in-sample the dual-signal edge is +4.04pp (21.77% → 25.81%);
out-of-sample it is **+13.92pp** (19.20% → 33.12%). This is the check README
Table 4 explicitly never ran, and it comes back positive — dual-signal did
not merely hold its in-sample advantage, it widened it on the untouched
2016-today period (which contains COVID and the 2022 bear, neither designed
around). This upgrades conclusion 2 from "unvalidated" to "OOS-consistent."

**Caveat, and it is a real one:** C made only **3 trades** in the 10-year
OOS window. A 33.12% result off 3 decisions is a favorable draw as much as a
robust edge — the same thin-sample fragility flagged throughout this
investigation. The direction is confirming; the magnitude is not
trustworthy. Read it as "dual-signal's edge did not evaporate out-of-sample,"
not "dual-signal earns 33%."

### 2. The stop's drawdown benefit is robust everywhere

B and D both cut Max DD to -64.77% in-sample (172/172 windows vs their own
base) and to -48.73% out-of-sample. The drawdown tool works regardless of
base strategy or sample. This is the most robust result in the whole
investigation and it holds here too.

### 3. The stop dominates the drawdown profile — entry rule becomes irrelevant to risk

Out-of-sample, B and D produce the **identical 8 exit dates** and the
**identical -48.73% Max DD**, despite completely different entry rules. Once
the GSPC 8%/60d stop is on, it fires before either trend signal would, so it
alone determines when you are out during crashes. The entry rule then only
affects *return* (via re-entry timing), not *risk*. Trade counts confirm it:
17.8 (B) vs 17.9 (D) in-sample, 8 vs 8 out-of-sample.

### 4. Combining is a drawdown-for-return TRADE on dual-signal, not a free improvement

This is the finding that complicates "just combine them":

- On the SMA base, the stop **helped return** out-of-sample: A → B is
  19.20% → 22.50% (+3.30pp) *and* -72.26% → -48.73% drawdown. A near-win on
  both axes.
- On the dual-signal base, the stop **cost return** out-of-sample: C → D is
  33.12% → 24.06% (**-9.06pp**) for the same -48.73% drawdown.

Dual-signal is a higher-return strategy that stays invested through more
upside; the stop's exits and cooldowns cut into that upside more than they
did on the lower-return SMA base. The in-sample data showed the same
direction but far smaller (-1.22pp); out-of-sample it is large.

So D is **not** strictly better than C. The choice between them is a pure
risk-tolerance trade:

| If you want... | Pick | OOS TWR | OOS Max DD |
| :--- | :-- | ---: | ---: |
| Maximum return | C (dual, no stop) | 33.12% | -69.96% |
| Maximum drawdown protection | D (dual + stop) | 24.06% | -48.73% |

Roughly: **D gives up ~9pp of out-of-sample return to remove ~21pp of
drawdown.** Whether that is worth it is not a backtest question.

## Bottom line on the two conclusions

1. **GSPC trailing stop** — confirmed as a robust drawdown tool, in and out
   of sample, on both base strategies. If a stop is used, GSPC/single-ticker/
   first-breach at ~8% is the configuration. Unchanged.

2. **Dual-signal for the trend** — now has genuine out-of-sample support
   (edge survived and grew), upgraded from "current default, unvalidated" to
   "OOS-consistent," subject to the thin-trade-count caveat. It remains
   slightly worse than SMA on drawdown, which is exactly the weakness the
   GSPC stop addresses.

The two pair coherently — dual-signal for return, GSPC stop for the drawdown
dual-signal doesn't fix — but combining them (D) is a real return sacrifice,
not a free upgrade over dual-signal alone (C). The honest framing is three
distinct options, not one recommended stack:
- **C** — highest return, deepest drawdown (aggressive).
- **D** — moderate return, shallowest drawdown (defensive).
- **A/B** — the current live baseline and its stopped version, both lower
  return than the dual-signal pair in every sample measured here.
