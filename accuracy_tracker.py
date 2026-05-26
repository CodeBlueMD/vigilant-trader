"""Positional signal accuracy tracking.

Records every confirmed signal and evaluates outcomes at 30 and 60 days.
Monthly report aggregates win rates by confidence level and ticker.
"""
from __future__ import annotations

import time
from typing import Any

from config import log
from data_fetcher import fetch_latest_price
from database import (
    get_conn,
    open_positional_signals,
    record_positional_signal,
    update_signal_evaluation,
)


def log_signal(
    ticker: str,
    signal_type: str,
    confidence: str,
    entry_price: float,
    gates: list,
    atr_stop: float | None,
    suggested_position_usd: float | None,
    ai_narrative: str,
    entry_range_high: float | None = None,
    entry_range_low: float | None = None,
    volatility_tier: str = "",
) -> int:
    signal_id = record_positional_signal(
        ticker=ticker,
        signal_type=signal_type,
        confidence=confidence,
        entry_price=entry_price,
        gates_fired=[g.name for g in gates if g.passed],
        atr_stop=atr_stop,
        suggested_position_usd=suggested_position_usd,
        ai_narrative=ai_narrative,
        entry_range_high=entry_range_high,
        entry_range_low=entry_range_low,
        volatility_tier=volatility_tier,
    )
    log.info("Logged signal #%d: %s %s (%s)", signal_id, ticker, signal_type, confidence)
    return signal_id


def evaluate_open_signals() -> int:
    """Evaluate 30d and 60d outcomes for all open signals. Returns count updated."""
    signals = open_positional_signals()
    updated = 0
    now = time.time()

    for s in signals:
        ticker = s["ticker"]
        entry_price = s.get("entry_price") or 0
        signal_ts = s.get("signal_ts") or 0
        signal_id = s["id"]
        signal_type = s.get("signal_type") or "bullish"

        current_price = fetch_latest_price(ticker)
        if current_price is None or entry_price == 0:
            continue

        age_days = (now - signal_ts) / 86400
        return_pct = (current_price - entry_price) / entry_price * 100
        outcome = "win" if (
            (signal_type == "bullish" and return_pct > 0) or
            (signal_type == "bearish" and return_pct < 0)
        ) else "loss"

        if age_days >= 30 and s.get("eval_30d_ts") is None:
            update_signal_evaluation(signal_id, "30d", current_price, round(return_pct, 2), outcome)
            log.info("30d eval %s #%d: %+.1f%% (%s)", ticker, signal_id, return_pct, outcome)
            updated += 1

        if age_days >= 60 and s.get("eval_60d_ts") is None:
            update_signal_evaluation(signal_id, "60d", current_price, round(return_pct, 2), outcome)
            log.info("60d eval %s #%d: %+.1f%% (%s)", ticker, signal_id, return_pct, outcome)
            updated += 1

    return updated


def monthly_report_data(months_back: int = 1) -> dict[str, Any]:
    """Aggregate accuracy stats for the past N months."""
    cutoff = time.time() - months_back * 30 * 86400
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positional_signals WHERE signal_ts >= ? ORDER BY signal_ts DESC",
            (cutoff,),
        ).fetchall()
    rows = [dict(r) for r in rows]

    if not rows:
        return {"total_signals": 0}

    evaluated_30d = [r for r in rows if r.get("eval_30d_outcome")]
    wins_30d = [r for r in evaluated_30d if r.get("eval_30d_outcome") == "win"]
    evaluated_60d = [r for r in rows if r.get("eval_60d_outcome")]
    wins_60d = [r for r in evaluated_60d if r.get("eval_60d_outcome") == "win"]

    by_confidence: dict[str, dict] = {}
    for r in evaluated_30d:
        conf = r.get("confidence") or "Unknown"
        by_confidence.setdefault(conf, {"total": 0, "wins": 0})
        by_confidence[conf]["total"] += 1
        if r.get("eval_30d_outcome") == "win":
            by_confidence[conf]["wins"] += 1

    by_ticker: dict[str, dict] = {}
    for r in evaluated_30d:
        t = r["ticker"]
        by_ticker.setdefault(t, {"total": 0, "wins": 0, "returns": []})
        by_ticker[t]["total"] += 1
        by_ticker[t]["returns"].append(r.get("eval_30d_return_pct") or 0)
        if r.get("eval_30d_outcome") == "win":
            by_ticker[t]["wins"] += 1

    ticker_summary = sorted(
        [
            {
                "ticker": t,
                "total": d["total"],
                "wins": d["wins"],
                "win_rate_pct": round(d["wins"] / d["total"] * 100, 1),
                "avg_return_pct": round(sum(d["returns"]) / len(d["returns"]), 2),
            }
            for t, d in by_ticker.items()
        ],
        key=lambda x: x["avg_return_pct"],
        reverse=True,
    )

    return {
        "total_signals": len(rows),
        "evaluated_30d": len(evaluated_30d),
        "win_rate_30d_pct": round(len(wins_30d) / len(evaluated_30d) * 100, 1) if evaluated_30d else None,
        "evaluated_60d": len(evaluated_60d),
        "win_rate_60d_pct": round(len(wins_60d) / len(evaluated_60d) * 100, 1) if evaluated_60d else None,
        "by_confidence": by_confidence,
        "by_ticker": ticker_summary,
        "pending_evaluation": len(rows) - len(evaluated_30d),
    }
