"""Alert orchestration — emergency detection + dispatching.

Public surface:
* check_and_dispatch_emergencies() — call after each sentiment + decision cycle.
"""
from __future__ import annotations

import time
from typing import Any

from config import log
from database import alerts_in_window, record_alert, state_get
from email_system import send_emergency_alert


# Suppress duplicate alerts for the same headline within this many seconds
DEDUP_WINDOW_SECONDS = 6 * 60 * 60  # 6h


def _was_recently_alerted(headline: str) -> bool:
    needle = (headline or "").strip().lower()
    if not needle:
        return True
    for row in alerts_in_window(DEDUP_WINDOW_SECONDS):
        existing = (row.get("headline") or "").strip().lower()
        if existing == needle:
            return True
    return False


def check_and_dispatch_emergencies() -> list[dict]:
    """Scan latest geo state + per-ticker verdicts for AI-confirmed emergencies."""
    geo = state_get("geo_state") or {}
    verdicts = state_get("verdicts") or {}

    fired: list[dict] = []

    # 1. Geo / macro emergencies
    for hit in geo.get("confirmed_emergencies") or []:
        headline = hit.get("headline", "")
        if _was_recently_alerted(headline):
            continue
        payload = {
            "headline": headline,
            "severity": hit.get("severity", "high"),
            "reason": hit.get("reason", ""),
            "ticker": "GLOBAL",
            "verdict": _global_verdict(verdicts, geo),
        }
        if send_emergency_alert(payload):
            record_alert("GLOBAL", payload["severity"], "geo", headline, payload)
            fired.append(payload)

    # 2. Per-ticker urgent verdicts
    for ticker, v in verdicts.items():
        urgency = (v.get("ai_urgency") or "Monitor").lower()
        bias = (v.get("bias") or "Neutral")
        if urgency in ("alert", "critical") and bias in ("Bearish", "Cautious"):
            headline = (
                f"{ticker} flagged {urgency.upper()} by AI: bias {bias}, "
                f"score {v.get('score')}"
            )
            if _was_recently_alerted(headline):
                continue
            payload = {
                "headline": headline,
                "severity": "critical" if urgency == "critical" else "high",
                "reason": v.get("ai_reasoning", ""),
                "ticker": ticker,
                "verdict": v,
            }
            if send_emergency_alert(payload):
                record_alert(
                    ticker, payload["severity"], "ticker", headline, payload
                )
                fired.append(payload)

    if fired:
        log.warning("Dispatched %d emergency alert(s)", len(fired))
    return fired


def _global_verdict(verdicts: dict, geo: dict) -> dict:
    """Compose a synthetic 'GLOBAL' verdict for geo alerts."""
    digest = (geo or {}).get("ai_digest") or {}
    risk_levels = [v.get("ai_risk_level") for v in (verdicts or {}).values()]
    return {
        "ai_bias": digest.get("sentiment_label", "Neutral"),
        "ai_confidence": "Medium",
        "ai_reasoning": digest.get("summary", ""),
        "ai_action": "Monitor exposure; consider hedges if risk escalates.",
        "ai_risk_factors": digest.get("key_themes", []) or risk_levels,
        "bias": digest.get("sentiment_label", "Neutral"),
    }
