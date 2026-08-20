### 1. Strategy ranking is unchanged (TWR is cash-flow-invariant)

*172 rolling 26-year windows, 3x ^NDX, S&P signal, pre-tax. Avg TWR compared: lump sum vs $2,000/mo DCA — identical by construction (TWR strips cash flows), which is why the strategy CHOICE does not change.*

| Cfg | Strategy | Avg TWR (lump) | Avg TWR (DCA) | Max abs diff |
| :-- | :--- | ---: | ---: | ---: |
| C | Dual-signal, no stop (taxable pick) | 25.81% | 25.81% | 0.00e+00 pp |
| D | Dual-signal + stop 8/60 (tax-adv pick) | 24.59% | 24.59% | 0.00e+00 pp |

### 2. Dollar outcome under $10,000 + $2,000/month

*Same 172 windows. Each window contributes $10,000 up front then $2,000/mo for 26 years (~$632,000 invested per window). Final Value / ROI are money-weighted; Worst DD is peak-to-trough on the growing balance.*

| Cfg | Strategy | Median Final Value | Avg Final Value | Median ROI | Worst DD | Avg Trades |
| :-- | :--- | ---: | ---: | ---: | ---: | ---: |
| C | Dual-signal, no stop (taxable pick) | $51,567,404 | $54,048,791 | 8034% | -84.74% | 8.8 |
| D | Dual-signal + stop 8/60 (tax-adv pick) | $40,371,341 | $37,957,610 | 6268% | -64.37% | 17.9 |

### 3. Stop or no stop, by tax regime, under $2,000/month DCA

*Same 172 windows. Tax-advantaged account -> read pre-tax rows; taxable account -> read after-tax rows. C = no stop, D = + trailing stop 8/60. Tax realised on exits; contributions correctly added to cost basis.*

| Regime | Cfg | Avg TWR | Median Final Value | Median ROI | Worst DD |
| :--- | :-- | ---: | ---: | ---: | ---: |
| Pre-tax (tax-adv) | C | 25.81% | $51,567,404 | 8034% | -84.74% |
| Pre-tax (tax-adv) | D | 24.59% | $40,371,341 | 6268% | -64.37% |
| After-tax (taxable) | C | 23.80% | $34,684,700 | 5371% | -87.33% |
| After-tax (taxable) | D | 20.05% | $16,207,030 | 2456% | -66.58% |

**How to read this:**
- Table 1: DCA does not change *which* config wins — Avg TWR is identical to lump sum (max per-window diff is floating-point dust). The best-practice config is the same: dual-signal (C) taxable, dual-signal + stop (D) tax-advantaged.
- Table 2: what DCA *does* change — the accumulated dollars and the money-weighted ROI, plus a worst-case drawdown now measured on a much larger late-period balance. The stop (D) trades a little ROI for a shallower Worst DD, same tradeoff as lump sum.
- Worst DD is still a deep number: leverage, not the contribution schedule, sets the drawdown depth. DCA cushions the *early* years (cheap accumulation) but does not shrink the percentage crash on the balance you have built.