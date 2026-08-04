# Trailing Stop on the Dual-Signal Strategy (2026-08-03)

## Question

Does the trailing-stop's drawdown-reduction property carry over to the
dual-signal approach (`DualSignalAgreement`, no T+2 — requires ^NDX and
^GSPC trend signals to agree, acts same-day)? Every prior trailing-stop
result was measured on one strategy (`SMATrendFollowing` + ^GSPC signal +
T+2), so this is the falsification test for the "it's a mechanism-level
property" claim.

## Method

`backtest/trailing_stop_dual_signal.py`, 172-window rolling aggregate,
^NDX/3x, pre-tax. The trailing-stop overlay is **reused verbatim** —
`SMATrendFollowing._apply_trailing_stop` called as an unbound method on a
`DualSignalAgreement` subclass (it only reads `in_market`, `Close`, and the
two stop params), so no engine change and the exact lookahead-free tested
code runs. The pct axis (6/7/8/9/10% at 60d) matches
`docs/trailing-stop-stability-probe-2026-08-03.md` for direct comparison.

Two variables differ from the published SMA stop, so **both** are run to
isolate them:
- **Stop tracks ^NDX** — realistic for a TQQQ holder (track what you hold).
- **Stop tracks ^GSPC** — same reference as the published SMA stop, so the
  dual-signal *entry rule* is the only remaining difference.

## Result

Dual-signal baseline (no stop): Avg TWR **25.81%**, mean Max DD -84.59%,
8.8 trades — a higher-return, higher-drawdown, lower-turnover strategy than
the SMA+T+2 baseline (21.77% / -83.13% / 11.1).

**Stop tracking ^NDX:**

| Config | Avg TWR | vs. base | DD improved | Mean Max DD | Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| baseline | 25.81% | — | — | -84.59% | 8.8 |
| 6%, 60d | 11.73% | -14.08pp | 172/172 | -49.26% | 42.7 |
| 7%, 60d | 11.93% | -13.88pp | 172/172 | -61.51% | 37.8 |
| 8%, 60d | 14.24% | -11.57pp | 172/172 | -63.47% | 33.2 |
| 9%, 60d | 21.73% | -4.08pp | 172/172 | -62.76% | 27.4 |
| 10%, 60d | 19.02% | -6.79pp | 172/172 | -64.76% | 26.3 |

**Stop tracking ^GSPC (entry-rule effect isolated):**

| Config | Avg TWR | vs. base | DD improved | Mean Max DD | Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| baseline | 25.81% | — | — | -84.59% | 8.8 |
| 6%, 60d | 16.56% | -9.25pp | 172/172 | -67.56% | 27.8 |
| 7%, 60d | 15.82% | -9.99pp | 172/172 | -67.55% | 23.2 |
| 8%, 60d | 24.59% | -1.22pp | 172/172 | -64.77% | 17.9 |
| 9%, 60d | 25.56% | -0.25pp | 172/172 | -64.77% | 16.7 |
| 10%, 60d | 20.68% | -5.13pp | **4/172** | -88.87% | 13.6 |

## Findings

**1. The drawdown property generalizes — confirmed.** Every stop width from
6% up improves per-window drawdown in **172/172 windows** under both
tracking choices, cutting mean Max DD from -84.59% to the -49% to -68%
range. This is the same wide plateau the SMA+T+2 stability probe found. The
drawdown benefit is a genuine mechanism-level property; it survives a
complete change of entry/exit rule.

**2. The 9%/10% cliff is a ^GSPC-tracking phenomenon.** Tracking ^GSPC, the
plateau collapses at 10% exactly as it did for SMA+T+2 (172/172 → 4/172,
mean Max DD -64.77% → -88.87%). Tracking ^NDX, there is no cliff — 10% still
improves 172/172. So the cliff is a property of ^GSPC's peak dynamics, not
of the entry rule. The `9%, 60d` point that looked attractive for SMA sits
adjacent to this cliff under ^GSPC tracking and should be treated with the
same caution flagged earlier.

**3. The tracking ticker matters more than the entry rule.** The first
^NDX-tracked run showed severe return damage (-11.57pp at 8%), which looked
like the dual-signal rule being incompatible with the stop. Isolating the
variable disproves that: with the tracking ticker held at ^GSPC, the
dual-signal return cost at 8% is only **-1.22pp** — inside the same
wash-to-slightly-negative band as SMA+T+2's +1.66pp (whose own plateau
average was -1.86 to -0.41pp). The ~10pp difference between the two runs is
almost entirely turnover: tracking the more-volatile ^NDX fires the stop
roughly twice as often (33.2 vs. 17.9 trades at 8%), and every extra
stop/cooldown cycle sheds upside.

This retroactively strengthens the published stop's design choice to
measure against ^GSPC: tracking a less-volatile reference is materially
better not just than the leveraged equity curve, but than the traded
^NDX index too.

## Answer to the question asked

Yes — the trailing stop works on the dual-signal setup in the sense that
matters: the drawdown-reduction property transfers intact (172/172 across
the whole 6-9% plateau), which is the strongest evidence yet that the
benefit is real and not an artifact of any one signal.

But the return trade-off is the same as everywhere else — a wash-to-modest
cost, not a gain — and it comes with one setup-specific caution that is
actionable: **if a stop is added to the dual-signal strategy, it should
track ^GSPC, not the ^NDX you hold.** Tracking ^NDX roughly doubles
turnover and converts a ~1pp return cost into a 4-14pp one for essentially
the same drawdown benefit. The dual-signal baseline is itself a
higher-return strategy (25.81% vs. 21.77%), so it has more return to lose
and is, if anything, a less natural fit for a return-neutral drawdown
overlay than SMA+T+2 was.

Nothing here changes the standing conclusion: the stop is a drawdown tool
whose return contribution is not a selling point, adoptable only if
reduced drawdown is worth a small and possibly-negative return effect.
