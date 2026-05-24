"""Unified decision engine.

Combines:
* technical signals from technical_analysis.compute_signals
* news sentiment from sentiment_engine state
* an AI verdict from ai_engine.generate_verdict

Produces one composite verdict per ticker.
"""
from __future__ import annotations

import time
from typing import Any

from ai_engine import ai_engine
from config import TICKERS, log
from data_fetcher import fetch_intraday, latest_quote
from database import (
    record_ai_verdict,
    record_divergence,
    state_get,
    state_set,
)
from technical_analysis import compute_signals


_BIAS_LEVELS = {"Bearish": -2, "Cautious": -1, "Neutral": 0, "Bullish": 1}


def _quant_bias(signals: dict, sentiment_score: float) -> tuple[str, float]:
    """Compute a quant-only bias label + composite score (-1..1)."""
    rsi = signals.get("rsi") or 50
    crossover = signals.get("ema_crossover") or "none"
    pattern = signals.get("pattern") or "none"

    score = 0.0
    # RSI contribution
    if rsi >= 70:
        score -= 0.4
    elif rsi <= 30:
        score += 0.4
    else:
        score += (50 - rsi) / 100  # mean-revert lean

    # crossover
    if crossover == "bullish":
        score += 0.5
    elif crossover == "bearish":
        score -= 0.5
    elif crossover == "above":
        score += 0.15
    elif crossover == "below":
        score -= 0.15

    # patterns
    if pattern in ("bullish_engulfing", "hammer"):
        score += 0.3
    elif pattern in ("bearish_engulfing", "shooting_star"):
        score -= 0.3

    # blend technicals 60% / sentiment 40%
    composite = (score * 0.6) + (sentiment_score * 0.4)
    composite = max(-1.0, min(1.0, composite))

    if composite >= 0.35:
        label = "Bullish"
    elif composite >= 0.1:
        label = "Neutral"
    elif composite >= -0.25:
        label = "Cautious"
    else:
        label = "Bearish"
    return label, round(composite, 3)


def _level_diff(a: str, b: str) -> int:
    return abs(_BIAS_LEVELS.get(a, 0) - _BIAS_LEVELS.get(b, 0))


def _more_conservative(a: str, b: str) -> str:
    """Return whichever bias is further toward bearish."""
    return min([a, b], key=lambda x: _BIAS_LEVELS.get(x, 0))


# -----------------------------------------------------------------------

def get_unified_verdict(ticker: str, sentiment_state: dict | None = None) -> dict:
    """Compute a single verdict dict for one ticker."""
    sentiment_state = sentiment_state or state_get("sentiment_state", {}) or {}
    sent = sentiment_state.get(ticker, {}) or {}
    sent_score = float(sent.get("score", 0.0) or 0.0)
    sent_delta = float(sent.get("delta", 0.0) or 0.0)

    intraday = fetch_intraday(ticker, period="5d", interval="15m")
    signals = compute_signals(intraday)
    quote = latest_quote(ticker)

    quant_label, composite = _quant_bias(signals, sent_score)

    ai_verdict = ai_engine.generate_verdict(
        ticker=ticker,
        rsi=signals.get("rsi"),
        ema_crossover=signals.get("ema_crossover"),
        pattern=signals.get("pattern"),
        sentiment_score=sent_score,
        sentiment_delta=sent_delta,
        price=quote.get("price"),
        intraday_chg=quote.get("intraday_chg_pct"),
    )

    final_bias = quant_label
    divergence_note = ""
    if _level_diff(ai_verdict["bias"], quant_label) > 1:
        divergence_note = (
            f"AI says {ai_verdict['bias']} vs quant {quant_label} - using more "
            "conservative reading."
        )
        final_bias = _more_conservative(ai_verdict["bias"], quant_label)
        log.warning("AI and quant signals diverge on %s: %s", ticker, divergence_note)
        record_divergence(ticker, quant_label, ai_verdict["bias"], divergence_note)

    out = {
        "ticker": ticker,
        "ts": time.time(),
        "price": quote.get("price"),
        "intraday_chg_pct": quote.get("intraday_chg_pct"),
        "rsi": signals.get("rsi"),
        "ema_crossover": signals.get("ema_crossover"),
        "pattern": signals.get("pattern"),
        "trend": signals.get("trend"),
        "sentiment_score": sent_score,
        "sentiment_delta": sent_delta,
        "ai_summary": sent.get("ai_summary"),
        "ai_themes": sent.get("ai_themes", []),
        "ai_risk_level": sent.get("ai_risk_level"),
        "score": composite,
        "quant_bias": quant_label,
        "bias": final_bias,                 # final blended bias
        "ai_bias": ai_verdict["bias"],
        "ai_confidence": ai_verdict["confidence"],
        "ai_action": ai_verdict["action"],
        "ai_reasoning": ai_verdict["reasoning"],
        "ai_risk_factors": ai_verdict["risk_factors"],
        "ai_urgency": ai_verdict["urgency"],
        "divergence_note": divergence_note,
        "disclaimer": ai_verdict.get("disclaimer", ""),
    }
    record_ai_verdict(ticker, out)
    return out


def run_decision_cycle() -> dict[str, dict]:
    out: dict[str, dict] = {}
    sentiment_state = state_get("sentiment_state", {}) or {}
    for ticker in TICKERS:
        try:
            out[ticker] = get_unified_verdict(ticker, sentiment_state)
        except Exception as e:  # noqa: BLE001
            log.warning("Decision cycle failed for %s: %s", ticker, e)
    state_set("verdicts", out)
    log.info("Decision cycle produced %d verdicts", len(out))
    return out
