"""yfinance networking helper that plays nicely with an egress proxy.

Some sandboxed/CI environments route outbound HTTPS through a MITM proxy that
rejects ``curl_cffi``'s browser-TLS *impersonation* (the connection is reset).
yfinance defaults to an impersonating session, which fails there. This helper
builds a plain (non-impersonating) ``curl_cffi`` session pointed at the proxy CA
bundle when a proxy is configured, and otherwise returns ``None`` so yfinance
uses its normal defaults on an unrestricted machine.

It also wraps ``yf.download`` in a bounded exponential backoff so transient
rate-limits (HTTP 429) get a few retries instead of failing on the first hit.
"""

from __future__ import annotations

import os
import time

import pandas as pd

_CA_ENV_VARS = ("CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")
_DEFAULT_CA = "/root/.ccr/ca-bundle.crt"


def _ca_bundle() -> str | None:
    for var in _CA_ENV_VARS:
        path = os.environ.get(var)
        if path and os.path.exists(path):
            return path
    return _DEFAULT_CA if os.path.exists(_DEFAULT_CA) else None


def make_session():
    """Return a proxy-aware curl_cffi session, or None to use yfinance defaults."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return None
    try:
        from curl_cffi import requests as cr
    except Exception:
        return None
    kwargs = {"proxies": {"https": proxy, "http": proxy}}
    ca = _ca_bundle()
    if ca:
        kwargs["verify"] = ca
    # Deliberately no impersonate=... : the proxy resets impersonated TLS.
    return cr.Session(**kwargs)


def download(tickers, *, max_retries: int = 4, base_backoff: float = 8.0, **kwargs):
    """``yf.download`` with a proxy-aware session and bounded backoff retries."""
    import yfinance as yf

    session = make_session()
    if session is not None:
        kwargs.setdefault("session", session)
    kwargs.setdefault("progress", False)
    kwargs.setdefault("auto_adjust", False)

    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            df = yf.download(tickers, **kwargs)
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001 - surfaced after retries
            last_err = e
        if attempt < max_retries - 1:
            time.sleep(base_backoff * (attempt + 1))
    if last_err is not None:
        raise RuntimeError(f"yfinance download failed for {tickers!r}: {last_err}")
    raise RuntimeError(
        f"yfinance returned no data for {tickers!r} after {max_retries} attempts "
        "(the egress IP may be rate-limited by Yahoo)."
    )
