"""Sunday weekly positional summary — trend table across all tickers."""
from __future__ import annotations

from ai_engine import ai_engine
from config import log
from email_system import send_weekly_summary
from positional_analyst import run_analysis_cycle


def run_weekly_summary() -> None:
    log.info("Running weekly positional summary")
    results = run_analysis_cycle()

    results_dicts = [
        {
            "ticker": r.ticker,
            "weekly_trend": r.signals.weekly_trend if r.signals else "flat",
            "signal_type": r.signal_type,
            "confidence": r.confidence,
        }
        for r in results
    ]

    narrative = ai_engine.generate_weekly_summary_narrative(results_dicts)
    sent = send_weekly_summary(results, narrative)
    log.info("Weekly summary email %s", "sent" if sent else "failed")
