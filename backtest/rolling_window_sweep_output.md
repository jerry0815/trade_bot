#### 10-Year Rolling Windows (365 windows, 1986-04-29–2016-08-28 starts)

| Cfg | Strategy | Avg CAGR | Med CAGR | Worst-window CAGR | % windows <0 | Avg Sharpe | Mean maxDD | Worst DD |
| :-- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | SMA+T+2 (baseline) | 23.6% | 23.6% | -4.5% | 0.8% | 0.66 | -69.2% | -83.4% |
| B | SMA+T+2 + GSPC stop 8/60 | 25.3% | 25.4% | -2.4% | 0.8% | 0.70 | -55.4% | -64.8% |
| C | Dual-signal (no T+2) | 28.4% | 29.6% | -6.7% | 1.4% | 0.71 | -69.2% | -84.9% |
| **D** | **Dual-signal + GSPC stop 8/60 (recommended)** | **26.5%** | 26.4% | **-2.8%** | **0.8%** | **0.72** | -55.4% | **-64.8%** |
| BH | Buy & Hold ^NDX 1x (index) | 13.6% | 13.9% | -8.4% | 7.7% | 0.67 | -53.9% | -82.9% |

*Rolling windows step monthly (overlapping), next-day-open execution, pre-tax, cash when out of market. A–D are 3× ^NDX (TQQQ exposure); BH is the unleveraged NASDAQ-100 index at 0% fee. Sharpe is annualized on daily returns at rf = 0 (252-day convention). Overlapping windows share most of their data, so this distribution understates true sampling variance.*

- **% windows <0** — share of rolling windows whose *annualized return* came out negative (a losing hold over that horizon); measures how *often* a bad window happened, not how deep (see the drawdown columns).
- **GSPC stop 8%/60d** — crash-protection trailing stop on the unleveraged S&P 500 (`^GSPC`): exit the day it closes 8% below its since-entry peak, then a 60-trading-day re-entry cooldown. Configs B and D use it; A and C do not.
