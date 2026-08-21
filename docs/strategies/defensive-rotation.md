# Defensive Rotation (dynamic momentum for the out-of-market sleeve)

[← Back to README](../../README.md) · Related: [Core Trend Signal](core-trend-signal.md) · [Trailing Stop](trailing-stop.md) · [Methodology](methodology.md)

The trend strategy sits **out of TQQQ ~30% of the time** (transitions and bears). Rather than earn cash there, `bot.py` computes the **126-day (6-month) momentum** of four defensive assets and suggests holding the **strongest** one:

| Asset | Role |
|---|---|
| **KMLM** | Managed futures — crisis-alpha / trend-following across commodities, FX, rates |
| **TLT** | 20+ yr Treasuries — deflationary / flight-to-safety bear hedge |
| **GLD** | Gold — inflation / currency-debasement hedge |
| **SHY** | 1–3 yr Treasuries — the cash-like floor (wins when nothing else has momentum) |

Because SHY is in the set, the rotation **defaults to ~cash** when every risk asset has negative momentum — so it only takes risk when something is actually trending.

> **Status: live display feature, not yet in the production backtest.** `bot.py`'s
> `get_current_defensive_rotation()` shows the winner in the daily report, but the
> [headline strategy numbers](methodology.md) model "out of market" as **cash**. So
> those numbers *understate* the full system if the rotation is followed — the
> results below are the first quantification of that gap.

---

## Backtest Results

Applied only during the production rule's out-of-market days (~30% of days), best-126-day-momentum asset held vs cash, on the reconstructed-TQQQ production path. **The absolute CAGRs are window-specific and simplified — read the *difference* (rotation − cash), not the levels.**

| Out-of-market sleeve | CAGR | Max DD | Sharpe |
| :--- | ---: | ---: | ---: |
| **3-asset (TLT/GLD/SHY), 2005–2026** | | | |
| Cash (baseline) | 20.5% | -49.2% | 0.55 |
| Defensive rotation | **25.2%** | -50.8% | **0.64** |
| **4-asset incl KMLM, 2021–2026** (matches live) | | | |
| Cash (baseline) | 15.4% | -48.8% | 0.45 |
| Defensive rotation | **25.7%** | **-41.3%** | **0.63** |

> **The rotation beats cash in both windows.** Over the longer 3-asset sample it adds
> **+4.7pp CAGR / +0.09 Sharpe** at ~the same drawdown. Over the 4-asset window that
> includes managed futures (KMLM) it adds **+10pp CAGR / +0.18 Sharpe *and cuts the
> drawdown* −49% → −41%** — because in the 2022 bear it rotated toward KMLM/GLD
> momentum and **dodged the TLT bond crash** a cash-or-bonds sleeve would have taken.
> That is exactly the crisis-alpha behavior defensive momentum is supposed to provide,
> and it is a *positive* result — in contrast to the [options overlay](options-overlay.md), which was not.

## Caveats — why this is promising, not proven

- **Short samples**, especially the 4-asset one: **KMLM only launched late 2020**, so
  the managed-futures result rests on essentially a *single* major out-period (2022).
  Low statistical confidence; the +10pp is one good outcome, not a distribution. The
  3-asset 2005–2026 sample is more credible and still positive.
- **Defensive sleeve only** — this changes what you hold *when already out* of TQQQ;
  it does not touch the in-market (trend) behavior.
- **Turnover** — modeled with daily momentum rebalancing; a real monthly
  implementation would trade less. The winner changes slowly (126-day momentum), so
  this is a second-order effect.
- **Not yet integrated into the production rolling backtest.** The natural next step
  is to wire it in with long-history proxies (e.g. managed-futures / long-bond mutual
  funds pre-ETF) so it gets the same 26-year rolling treatment as the core signals.

## Further reading

- [`bot.py`](../../bot.py) `get_current_defensive_rotation()` — the live logic.
- [Trailing Stop](trailing-stop.md) — the other crash-protection layer.
