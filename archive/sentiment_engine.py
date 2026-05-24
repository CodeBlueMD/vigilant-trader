"""Sentiment engine — keyword baseline blended with AI digest.

Public surface:
* run_sentiment_poll() -> dict[ticker -> sentiment payload]
* run_geo_poll()       -> dict (geo headlines + AI digest + emergency hits)
"""
from __future__ import annotations

import time
from typing import Any

from ai_engine import ai_engine
from config import TICKERS, log
from data_fetcher import fetch_geo_headlines, fetch_news_for_ticker
from database import state_get, state_set


# Keywords for fast lexical baseline ------------------------------------

_BULLISH = {
    "beat", "beats", "surge", "rally", "record", "upgrade", "buyback",
    "strong", "growth", "profit", "raises", "outperform", "bullish",
}
_BEARISH = {
    "miss", "misses", "plunge", "drop", "fall", "downgrade", "loss", "weak",
    "warning", "halt", "lawsuit", "probe", "fraud", "bankruptcy", "bearish",
    "recession", "default",
}

EMERGENCY_KEYWORDS = {
    "halt", "circuit breaker", "crash", "war", "invasion", "missile",
    "terror", "attack", "default", "collapse", "bankruptcy", "rate cut",
    "rate hike", "emergency", "shock", "evacuate", "sanction", "tariff",
}


def _keyword_score(headlines: list[str]) -> float:
    if not headlines:
        return 0.0
    pos = neg = 0
    for h in headlines:
        text = (h or "").lower()
        pos += sum(1 for w in _BULLISH if w in text)
        neg += sum(1 for w in _BEARISH if w in text)
    total = pos + neg
    if total == 0:
        return 0.0
    return max(-1.0, min(1.0, (pos - neg) / total))


def _emergency_keyword_hits(headlines: list[str]) -> list[str]:
    out = []
    for h in headlines:
        low = (h or "").lower()
        if any(k in low for k in EMERGENCY_KEYWORDS):
            out.append(h)
    return out


# -----------------------------------------------------------------------

def run_sentiment_poll() -> dict[str, dict]:
    """Poll news per ticker, blend keyword + AI sentiment, store and return state."""
    out: dict[str, dict] = {}
    previous = state_get("sentiment_state", {}) or {}

    for ticker in TICKERS:
        try:
            news = fetch_news_for_ticker(ticker, limit=10)
        except Exception as e:  # noqa: BLE001
            log.warning("News fetch failed for %s: %s", ticker, e)
            news = []

        headlines = [n["headline"] for n in news if n.get("headline")]

        kw_score = _keyword_score(headlines)
        ai = ai_engine.digest_headlines(headlines, ticker) if headlines else None

        if ai:
            final_score = (kw_score * 0.3) + (float(ai.get("score", 0.0)) * 0.7)
        else:
            final_score = kw_score

        prev = previous.get(ticker, {})
        prev_score = float(prev.get("score", 0.0) or 0.0)
        delta = final_score - prev_score

        out[ticker] = {
            "ticker": ticker,
            "score": round(final_score, 3),
            "delta": round(delta, 3),
            "kw_score": round(kw_score, 3),
            "ai_score": round(float(ai["score"]), 3) if ai else None,
            "ai_summary": (ai or {}).get("summary"),
            "ai_themes": (ai or {}).get("key_themes", []),
            "ai_risk_level": (ai or {}).get("risk_level"),
            "ai_label": (ai or {}).get("sentiment_label"),
            "headlines": headlines[:5],
            "news": news[:5],
            "ts": time.time(),
        }

    state_set("sentiment_state", out)
    log.info("Sentiment poll updated for %d tickers", len(out))
    return out


def run_geo_poll() -> dict[str, Any]:
    """Geopolitical / macro headline poll with AI emergency triage."""
    headlines = fetch_geo_headlines(limit=15)
    titles = [h["headline"] for h in headlines]
    kw_score = _keyword_score(titles)

    ai_digest = ai_engine.digest_headlines(titles, "Global Macro") if titles else None

    # Emergency triage: keyword hit -> AI confirms severity
    raw_hits = _emergency_keyword_hits(titles)
    confirmed = []
    for hl in raw_hits:
        cls = ai_engine.classify_emergency(hl)
        if cls.get("is_emergency") and cls.get("severity") in ("high", "critical"):
            confirmed.append({"headline": hl, **cls})

    payload = {
        "ts": time.time(),
        "headlines": headlines,
        "kw_score": round(kw_score, 3),
        "ai_digest": ai_digest,
        "raw_emergency_hits": raw_hits,
        "confirmed_emergencies": confirmed,
    }
    state_set("geo_state", payload)
    log.info(
        "Geo poll: %d headlines, %d raw emergencies, %d confirmed",
        len(headlines),
        len(raw_hits),
        len(confirmed),
    )
    return payload
