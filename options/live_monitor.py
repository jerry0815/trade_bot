"""Daily live scanner for the **collar** overlay (alert-only).

Computes today's trend regime and equity allocation, then — following the
backtest's conclusion — emits the **collar** the strategy would run: on the TQQQ
you hold, sell a ~20Δ call and buy a ~15Δ put (~30 DTE), rolled monthly in the
bull/transition regimes and closed in a bear. It deliberately does **not** emit
the old two-sided matrix (covered calls / cash-secured puts / bull-put spreads);
the research found the short-put structures add tail risk and the collar wins.

This is a *monitor*, not an order router: it tells you what to place. A human
places the trades against the live chain. The model strikes below are guidance at
TQQQ's realistic vol (~2.5× ^VXN); the actual legs should be the ~20Δ call and
~15Δ put on the real chain (surfaced best-effort when reachable). IV never needs
computing for the decision — the chain hands you the deltas.

    python -m options.live_monitor
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .greeks import GreeksEngine
from .regime import MarketRegime, RegimeParams, classify_regime
from .run_benchmark import _atr, _rsi
from .iv_loader import compute_iv_rank

# Collar parameters (mirror OverlayConfig defaults for the winning model).
COLLAR_CALL_DELTA = 0.20
COLLAR_PUT_DELTA = 0.15
COLLAR_DTE = 30
# ^VXN is the 1x Nasdaq-100 vol index; TQQQ (3x) realizes ~2.5x that, so lift the
# vol before selecting model strikes (see OverlayConfig.pricing_iv_mult).
PRICING_IV_MULT = 2.5


def _latest_frame(params: RegimeParams) -> pd.DataFrame:
    from ._net import download

    tqqq = download("TQQQ", period="2y")
    vxn = download("^VXN", period="2y")
    for frame in (tqqq, vxn):
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)

    df = pd.DataFrame(index=tqqq.index)
    df["Close"] = tqqq["Close"]
    df["High"] = tqqq["High"]
    df["Low"] = tqqq["Low"]
    df["SMA"] = df["Close"].rolling(params.sma_period, min_periods=params.sma_period).mean()
    df["ATR"] = _atr(tqqq, params.atr_period)
    df["RSI"] = _rsi(df["Close"], params.rsi_period)
    iv = compute_iv_rank(vxn["Close"])
    df["IV"] = iv["IV"].reindex(df.index).ffill()
    df["IV_Rank"] = iv["IV_Rank"].reindex(df.index).ffill()
    return df.dropna(subset=["Close", "SMA", "ATR", "IV_Rank"])


def _collar_structure_lines(S: float, iv_pct: float, r: float = 0.045) -> list[str]:
    """Model-guidance strikes for the collar, priced at TQQQ's realistic vol.
    Pure/offline-testable."""
    sigma = iv_pct / 100.0 * PRICING_IV_MULT
    T = COLLAR_DTE / 365.0
    Kc, gc = GreeksEngine.get_strike_for_delta(S, T, r, sigma, COLLAR_CALL_DELTA, "call")
    Kp, gp = GreeksEngine.get_strike_for_delta(S, T, r, sigma, COLLAR_PUT_DELTA, "put")
    credit = gc["price"] * 100
    debit = gp["price"] * 100
    net = credit - debit
    net_word = "net credit" if net >= 0 else "net debit"
    return [
        f"• Sell {COLLAR_DTE}-DTE call ~{COLLAR_CALL_DELTA:.2f}Δ  →  strike ≈ {Kc}"
        f"   (est. credit ${credit:,.0f}/contract)",
        f"• Buy  {COLLAR_DTE}-DTE put  ~{COLLAR_PUT_DELTA:.2f}Δ  →  strike ≈ {Kp}"
        f"   (est. debit ${debit:,.0f}/contract)",
        f"• {net_word} ≈ ${abs(net):,.0f}/contract  |  one collar per 100 shares of TQQQ held",
        "• Manage: roll at 21 DTE; hold the put through a transition; close the "
        "collar (both legs) on a bear signal — never sell puts.",
        "⚠️ Strikes are model guidance — place the actual ~0.20Δ call / ~0.15Δ put "
        "off the live chain and check the bid/ask.",
    ]


def _live_chain_lines(S: float, r: float = 0.045) -> list[str]:  # pragma: no cover - network
    """Best-effort: surface the real ~20Δ call and ~15Δ put from the live TQQQ
    chain near 30 DTE. Degrades gracefully to a single note on any failure."""
    try:
        import yfinance as yf

        tk = yf.Ticker("TQQQ")
        expiries = tk.options
        if not expiries:
            return []
        today = pd.Timestamp.utcnow().normalize().tz_localize(None)
        target = today + pd.Timedelta(days=COLLAR_DTE)
        expiry = min(expiries, key=lambda e: abs((pd.Timestamp(e) - target).days))
        dte = (pd.Timestamp(expiry) - today).days
        T = max(dte, 1) / 365.0
        chain = tk.option_chain(expiry)

        def pick(dfrac, kind, want_delta):
            best, best_gap = None, 1e9
            for _, row in dfrac.iterrows():
                iv = float(row.get("impliedVolatility", 0) or 0)
                if iv <= 0:
                    continue
                d = abs(GreeksEngine.calculate_greeks(S, float(row["strike"]), T, r, iv, kind)["delta"])
                gap = abs(d - want_delta)
                if gap < best_gap:
                    best, best_gap = row, gap
            return best

        c = pick(chain.calls, "call", COLLAR_CALL_DELTA)
        p = pick(chain.puts, "put", COLLAR_PUT_DELTA)
        if c is None or p is None:
            return []
        return [
            f"🔗 **Live chain** (exp {expiry}, {dte} DTE):",
            f"   call {c['strike']:.0f}  bid {c['bid']:.2f} / ask {c['ask']:.2f}",
            f"   put  {p['strike']:.0f}  bid {p['bid']:.2f} / ask {p['ask']:.2f}",
        ]
    except Exception as exc:
        return [f"🔗 Live chain unavailable ({type(exc).__name__}); use the model strikes above."]


def build_report(params: RegimeParams = RegimeParams(), with_chain: bool = True) -> str:
    df = _latest_frame(params)
    row = df.iloc[-1]
    S = float(row["Close"])
    st = classify_regime(S, float(row["SMA"]), float(row["ATR"]),
                         float(row["IV_Rank"]), float(row["RSI"]), params)

    regime_emoji = {
        MarketRegime.BULL_EXPANSION: "🟩",
        MarketRegime.TRANSITION_BAND: "🟨",
        MarketRegime.BEAR_DEFENSE: "🟥",
    }[st.regime]
    alloc = {1.0: "100% TQQQ", 0.5: "50% TQQQ / 50% SGOV", 0.0: "100% SGOV / cash"}.get(
        st.target_equity_pct, f"{st.target_equity_pct*100:.0f}% TQQQ")

    date_str = df.index[-1].strftime("%Y-%m-%d")
    lines = [
        f"📅 **Collar Overlay Monitor ({date_str})**",
        "--------------------------",
        f"📈 **TQQQ** {S:.2f} | SMA200 {row['SMA']:.2f} | ATR14 {row['ATR']:.2f}",
        f"• Regime bands: {st.lower_bound:.2f} — {st.upper_bound:.2f}",
        f"• IV (^VXN): {row['IV']:.2f}  |  RSI14: {row['RSI']:.1f}",
        "--------------------------",
        f"{regime_emoji} **REGIME: {st.regime.value}**",
        f"• Equity allocation: **{alloc}**",
    ]

    if st.regime == MarketRegime.BEAR_DEFENSE:
        lines += [
            "• Options: **NONE** — hold 100% cash/SGOV.",
            "--------------------------",
            "🎯 **ACTION**",
            "• Close any open collar (both legs). Do **not** sell puts here.",
        ]
    else:
        lines += [
            "• Options: **COLLAR** (sell call + buy put on the TQQQ you hold).",
            "--------------------------",
            "🎯 **TARGET STRUCTURE — COLLAR**",
            *_collar_structure_lines(S, float(row["IV"])),
        ]
        if with_chain:
            lines += _live_chain_lines(S)

    lines += [
        "--------------------------",
        "ℹ️ Alert only — a human confirms and places the trades. Not investment advice.",
    ]
    return "\n".join(lines)


def main():  # pragma: no cover - network + side effects
    report = build_report()
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if webhook:
        import requests
        requests.post(webhook, json={"content": report})
    else:
        print(report)


if __name__ == "__main__":  # pragma: no cover
    main()
