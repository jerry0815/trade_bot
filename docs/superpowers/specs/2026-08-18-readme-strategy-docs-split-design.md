# README → Strategy-Docs Split — Design

**Date:** 2026-08-18
**Goal:** Refactor the large single-file README into a lean overview + a set of per-strategy docs, so each feature/strategy is elaborated in one dedicated doc and the README keeps only the overview, a final-decision table, and a one-line-result index that links out.

## Motivation

The README has grown to ~307 lines carrying 8 detailed result tables, each with multi-paragraph narrative and caveat blocks. It interleaves overview material (what the bot does) with deep per-table analysis. A reader wanting the bottom line has to scroll past everything; a reader wanting one strategy's detail has to find it among the others.

## Principles

- **Pure move/reorganize.** No numbers are recomputed or edited. Every table and narrative block is relocated verbatim. Wording is only trimmed where the README keeps a condensed summary.
- **One feature = one doc.** Each strategy layer lives in exactly one strategy doc.
- **No content deleted.** Everything currently in the README lands in exactly one strategy doc (or stays in the README).
- **Existing dated finding docs stay untouched.** The new strategy docs summarize and link *down* to them.

## Target README structure

Keep (as-is or condensed):
- Title + Project Overview — keep as-is.
- **How It Works** — condense to a 3-layer overview: each layer gets 1–2 sentences + a link to its strategy doc. Keep the state-machine mermaid diagram and the "recommended action" summary paragraph. Deep per-layer formulas/justification move into the strategy docs.
- **Backtesting Methodology** — condense to a short summary + link to `docs/strategies/methodology.md` (full engine details).
- **Backtest Results** — replace all 8 tables with:
  1. A **Final Decision** table (the bot's recommended configuration + headline performance vs Buy & Hold baseline), and
  2. A **one-line-result + link index**: one line per feature stating its headline result and linking to its strategy doc.
- Changelog / Strategy Research & Theoretical Basis / System Architecture / Getting Started / Risk Disclaimer — keep as-is.

### Final Decision table (README)

Rows drawn verbatim from existing Table 4 / Table 8:

| Configuration | Account | Avg TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: |
| Dual-signal agreement (no stop) | Taxable | 25.81% | -84.95% | 9 |
| Dual-signal agreement + Trailing Stop 8%/60d | Tax-advantaged | 24.59% | -64.78% | 18 |
| Buy & Hold (baseline) | — | 3.10% | -99.98% | 1 |

*26-year rolling backtest, 172 windows.*

## New `docs/strategies/` docs

Each contains: the layer's mechanics (moved from README's How It Works), its table(s) + narrative (moved verbatim), and links down to the relevant existing dated finding docs.

1. `methodology.md` — backtest engine details (rolling windows, next-day-open execution, historical borrow rates, cash yield, the two drawdown metrics, backtest parameters).
2. `core-trend-signal.md` — SMA 200 + ATR mechanics + **Tables 1, 2, 3** with narrative → links to `optimization-analysis-2026-07-27.md`, `out-of-sample-validation-2026-07-28.md`.
3. `dual-signal-agreement.md` — Layer 2 mechanics (dual-signal vs T+2) + **Table 4** (signal-source comparison) with narrative + caveats → links to `trailing-stop-dual-signal-2026-08-03.md`, `trailing-stop-dual-breach-2026-08-03.md`.
4. `trailing-stop.md` — Layer 3 mechanics + **Table 5** (crash-event drawdown) with narrative; cross-references Table 4's overlay rows (in dual-signal doc) rather than duplicating them → links to the full `trailing-stop-*` chain + `combined-system-comparison-2026-08-03.md`, `overlay-comparison-rolling-2026-08-03.md`.
5. `velocity-stop.md` — **Table 6** with narrative + caveats → links to `velocity-stop-2026-08-06.md`.
6. `qqq-1x.md` — **Table 7** with narrative + caveats → links to `qqq-1x-comparison-2026-08-06.md`.
7. `tax-treatment.md` — **Table 8** with narrative + caveats → links to `taxable-account-2026-08-06.md`.
8. `global-equities.md` — **Table 9** (MSCI World + EM → VT splice) with reconstruction caveats → links to `vt-reconstruction-validation-2026-08-12.md`.

The **experimental options overlay** (`options/` package) is *not* given a new wrapper doc — `options/README.md` already is its dedicated doc. The README keeps a short "Experimental — Dynamic Two-Sided Options Overlay" section linking to it, plus a one-line row in the strategy-docs index.

> **Note (2026-08-18):** this refactor was first built on a stale `main` that predated Table 9 and the options overlay. It was rebuilt on the current `main`; Tables 1–8 were byte-identical, so docs 1–7 were reused unchanged, and `global-equities.md` + the options-overlay handling were added.

## Judgment calls

- **Table 4 placement:** lives in `dual-signal-agreement.md` (its primary purpose is signal-source comparison). `trailing-stop.md` cross-references its two overlay rows instead of duplicating the table.
- **Methodology** becomes its own doc rather than staying inline, since all strategy docs share it and it's not "overview."

## Non-goals

- No recomputation of any backtest number.
- No changes to `bot.py`, backtest scripts, or the existing dated finding docs.
- No unrelated README rewording beyond what the condense-and-link requires.

## Verification

- Every one of the 8 tables appears in exactly one strategy doc (grep for a distinctive value from each).
- Every intra-README anchor link and every `docs/` link still resolves.
- README renders: Final Decision table + index links all point to existing files.
