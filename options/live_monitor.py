"""Daily live scanner for the options overlay.

Computes today's regime (price trend x IV-Rank), the resulting equity allocation,
and the option structure the matrix calls for — with concrete target strikes and
deltas priced off the current ^VXN level. Emits a formatted report to stdout and,
if ``DISCORD_WEBHOOK`` is set, posts it there (mirroring ``bot.py``).

This is a *monitor*, not an order router: it tells you what the engine would do
today. Actual fills should be checked against the live chain
(``yfinance.Ticker("TQQQ").option_chain``), which this module surfaces when
reachable.

    python -m options.live_monitor
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .greeks import GreeksEngine
from .regime import (
    MarketRegime,
    OptionAction,
    RegimeParams,
    classify_regime,
)
from .run_benchmark import _atr, _rsi
from .iv_loader import compute_iv_rank


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


def _target_structure_lines(action: OptionAction, S: float, iv_pct: float,
                            params: RegimeParams, r: float = 0.045) -> list[str]:
    """Human-readable target strikes/deltas for the recommended structure."""
    sigma = iv_pct / 100.0
    if action == OptionAction.IDLE:
        return ["• No options active — hold the equity/SGOV sleeve."]
    if action == OptionAction.SELL_COVERED_CALL:
        T = 35 / 365
        K, g = GreeksEngine.get_strike_for_delta(S, T, r, sigma, params.cc_delta, "call")
        return [f"• Sell 35-DTE covered call ~{params.cc_delta:.2f}Δ  →  strike ≈ {K}",
                f"  est. credit ≈ ${g['price']*100:,.0f}/contract; close at 50% profit or 21 DTE"]
    if action == OptionAction.SELL_CASH_SECURED_PUT:
        T = 30 / 365
        K, g = GreeksEngine.get_strike_for_delta(S, T, r, sigma, params.csp_delta, "put")
        return [f"• Sell 30-DTE cash-secured put ~{params.csp_delta:.2f}Δ  →  strike ≈ {K}",
                f"  est. credit ≈ ${g['price']*100:,.0f}/contract; SGOV-collateralized; 50% TP / 21 DTE"]
    if action == OptionAction.SELL_BULL_PUT_SPREAD:
        T = 30 / 365
        sp = GreeksEngine.spread_strikes(S, T, r, sigma, params.bps_short_delta,
                                         params.bps_long_delta, "put")
        return [f"• Sell 30-DTE bull put spread  →  short {sp['short_strike']} / long {sp['long_strike']}",
                f"  est. credit ≈ ${sp['net_credit']*100:,.0f}/contract; 50% TP / 2x-credit stop / 21 DTE"]
    if action == OptionAction.BUY_PUT_DEBIT_SPREAD:
        T = 45 / 365
        long_K, lg = GreeksEngine.get_strike_for_delta(S, T, r, sigma, params.debit_long_delta, "put")
        short_K, sg = GreeksEngine.get_strike_for_delta(S, T, r, sigma, params.debit_short_delta, "put")
        debit = lg["price"] - sg["price"]
        return [f"• Buy 45-DTE put debit spread  →  long {long_K} / short {short_K}",
                f"  est. debit ≈ ${debit*100:,.0f}/contract; take +100% or exit if IVR>55; -50% stop"]
    return ["• (unrecognized action)"]


def build_report(params: RegimeParams = RegimeParams()) -> str:
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
        f"📅 **Options Overlay Monitor ({date_str})**",
        "--------------------------",
        f"📈 **TQQQ** {S:.2f} | SMA200 {row['SMA']:.2f} | ATR14 {row['ATR']:.2f}",
        f"• Regime bands: {st.lower_bound:.2f} — {st.upper_bound:.2f}",
        f"• IV (^VXN): {row['IV']:.2f}  |  IV-Rank(252d): {row['IV_Rank']:.1f}  |  RSI14: {row['RSI']:.1f}",
        "--------------------------",
        f"{regime_emoji} **REGIME: {st.regime.value}**",
        f"• Equity allocation: **{alloc}**",
        f"• Option signal: **{st.option_action.value}**",
        "--------------------------",
        "🎯 **TARGET OPTION STRUCTURE**",
        *_target_structure_lines(st.option_action, S, float(row["IV"]), params),
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
