"""Weekly outlook generator — assembles AI focus + per-ticker price projections,
then dispatches the weekly email."""
from __future__ import annotations

from typing import Any

from accuracy_tracker import record_monday_predictions
from ai_engine import ai_engine
from config import log
from database import state_get, state_set
from decision_engine import run_decision_cycle
from email_system import send_weekly_outlook
from sentiment_engine import run_geo_poll, run_sentiment_poll


def build_weekly_payload() -> dict[str, Any]:
    # Refresh inputs so the weekly email reflects current state.
    run_sentiment_poll()
    run_geo_poll()
    verdicts = run_decision_cycle()

    # Per-ticker weekly price projections (one AI call each).
    projections: dict[str, dict] = {}
    for ticker, v in verdicts.items():
        try:
            projections[ticker] = ai_engine.generate_weekly_projection(
                ticker=ticker,
                price=v.get("price"),
                rsi=v.get("rsi"),
                ema_crossover=v.get("ema_crossover"),
                pattern=v.get("pattern"),
                sentiment_score=v.get("sentiment_score", 0.0),
                bias=v.get("bias", "Neutral"),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Projection failed for %s: %s", ticker, e)
            projections[ticker] = {}

    tickers_data = list(verdicts.values())
    weekly_focus = ai_engine.generate_weekly_focus(tickers_data)
    geo = state_get("geo_state") or {}

    payload = {
        "verdicts": verdicts,
        "projections": projections,
        "weekly_focus": weekly_focus,
        "geo": geo,
    }
    state_set("weekly_payload", payload)
    return payload


def run_weekly_outlook() -> bool:
    payload = build_weekly_payload()
    ok = send_weekly_outlook(
        verdicts=payload["verdicts"],
        weekly_focus=payload["weekly_focus"],
        geo_state=payload["geo"],
        projections=payload["projections"],
    )
    log.info("Weekly outlook dispatch: %s", "OK" if ok else "FAILED")
    # Persist this Monday's predictions so Friday can score them and the
    # AI can learn from its own track record on subsequent runs.
    try:
        record_monday_predictions(payload["verdicts"], payload["projections"])
    except Exception as e:  # noqa: BLE001
        log.warning("Failed to record Monday predictions: %s", e)
    return ok
