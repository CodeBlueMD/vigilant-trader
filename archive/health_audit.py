"""Weekly self-audit. Runs Sunday 18:00 America/Toronto.

Inspects logs, DB, AI status, and live data feeds to produce a concise
health report email + an `audit_state` dict for the dashboard.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

from accuracy_tracker import overall_accuracy, recent_accuracy, trend_snapshot
from ai_engine import ai_engine
from config import (
    AI_DISCLAIMER,
    LOG_FILE,
    NEWSAPI_KEY,
    FINNHUB_KEY,
    TICKERS,
    log,
)
from data_fetcher import latest_quote
from database import alerts_in_window, get_conn, state_set
from email_system import _CSS, _send


WEEK_SECONDS = 7 * 24 * 60 * 60


# ------------------------------------------------------------------ log parser

_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] [^:]+: (.*)$")


def _parse_log_window(seconds: int = WEEK_SECONDS) -> dict[str, Any]:
    """Scan the log file for the last `seconds` window and tally key events."""
    if not os.path.exists(LOG_FILE):
        return {"available": False}
    cutoff = datetime.now() - timedelta(seconds=seconds)

    counts = {
        "ai_failures": 0,
        "email_failures": 0,
        "email_successes": 0,
        "sentiment_polls": 0,
        "decision_cycles": 0,
        "geo_polls": 0,
        "alerts_fired": 0,
        "errors": 0,
        "warnings": 0,
    }
    last_seen: dict[str, str | None] = {
        "sentiment_poll": None,
        "decision_cycle": None,
        "geo_poll": None,
        "ai_success": None,
        "ai_failure": None,
        "email_success": None,
    }

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = _LOG_TS_RE.match(line)
                if not m:
                    continue
                ts_s, level, msg = m.groups()
                try:
                    ts = datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if ts < cutoff:
                    continue

                if level == "ERROR":
                    counts["errors"] += 1
                elif level == "WARNING":
                    counts["warnings"] += 1

                if "AI backend" in msg and "failed" in msg:
                    counts["ai_failures"] += 1
                    last_seen["ai_failure"] = ts_s
                elif "Email sent" in msg:
                    counts["email_successes"] += 1
                    last_seen["email_success"] = ts_s
                elif "Email send failed" in msg:
                    counts["email_failures"] += 1
                elif "Sentiment poll updated" in msg:
                    counts["sentiment_polls"] += 1
                    last_seen["sentiment_poll"] = ts_s
                    last_seen["ai_success"] = ts_s
                elif "Decision cycle produced" in msg:
                    counts["decision_cycles"] += 1
                    last_seen["decision_cycle"] = ts_s
                elif "Geo poll" in msg:
                    counts["geo_polls"] += 1
                    last_seen["geo_poll"] = ts_s
                elif "Dispatched" in msg and "alert" in msg:
                    counts["alerts_fired"] += 1
    except Exception as e:  # noqa: BLE001
        log.warning("Log parse failed: %s", e)
        return {"available": False, "error": str(e)}

    return {"available": True, "counts": counts, "last_seen": last_seen}


# ------------------------------------------------------------------ checks

def _check_ai() -> dict[str, Any]:
    online = ai_engine.is_online()
    s = ai_engine.status
    return {
        "online": online,
        "backend": s.backend,
        "model": s.model,
        "last_latency_ms": s.last_latency_ms,
        "last_error": s.last_error,
    }


def _check_data_feeds() -> dict[str, Any]:
    statuses: dict[str, dict] = {}
    for t in TICKERS:
        try:
            q = latest_quote(t)
            statuses[t] = {
                "ok": q.get("price") is not None,
                "price": q.get("price"),
            }
        except Exception as e:  # noqa: BLE001
            statuses[t] = {"ok": False, "error": str(e)[:120]}
    healthy = sum(1 for s in statuses.values() if s["ok"])
    return {
        "tickers_healthy": healthy,
        "tickers_total": len(statuses),
        "newsapi_configured": bool(NEWSAPI_KEY),
        "finnhub_configured": bool(FINNHUB_KEY),
        "per_ticker": statuses,
    }


def _check_emails(log_data: dict) -> dict[str, Any]:
    counts = log_data.get("counts", {})
    last_seen = log_data.get("last_seen", {})
    return {
        "successes_week": counts.get("email_successes", 0),
        "failures_week": counts.get("email_failures", 0),
        "last_success": last_seen.get("email_success"),
    }


def _check_predictions() -> dict[str, Any]:
    overall = overall_accuracy(n=8)
    trend = trend_snapshot(window=4)
    per_ticker = []
    for t in TICKERS:
        s = recent_accuracy(t, n=8)
        if s.get("n", 0) == 0:
            continue
        per_ticker.append(s)
    # Count alerts fired this week
    week_alerts = list(alerts_in_window(WEEK_SECONDS))
    return {
        "overall": overall,
        "trend": trend,
        "per_ticker": per_ticker,
        "alerts_fired": len(week_alerts),
    }


def _build_action_items(
    log_data: dict,
    ai: dict,
    feeds: dict,
    emails: dict,
    preds: dict,
) -> list[str]:
    items: list[str] = []
    counts = log_data.get("counts", {})

    # AI health
    successes = counts.get("sentiment_polls", 0) + counts.get("decision_cycles", 0)
    failures = counts.get("ai_failures", 0)
    total_calls = successes + failures
    if total_calls > 0 and failures / total_calls > 0.20:
        items.append(
            f"AI failure rate {failures}/{total_calls} this week (>20%). "
            "Check Groq key, Ollama status, and timeout setting."
        )
    if not ai["online"]:
        items.append("AI is offline. Falling back to quant-only signals.")

    # Email
    if emails["failures_week"] > 0:
        items.append(
            f"{emails['failures_week']} email send failure(s) this week. "
            "Verify Gmail App Password and SMTP settings."
        )

    # Data feeds
    bad_tickers = [
        t for t, s in feeds["per_ticker"].items() if not s["ok"]
    ]
    if bad_tickers:
        items.append(
            f"No live price for: {', '.join(bad_tickers)}. "
            "Verify the symbol(s) on Yahoo Finance."
        )
    if not feeds["newsapi_configured"]:
        items.append(
            "NEWSAPI_KEY not set — macro/geopolitical headlines disabled."
        )
    if not feeds["finnhub_configured"]:
        items.append(
            "FINNHUB_KEY not set — relying on yfinance for ticker news only."
        )

    # Scheduler freshness
    last_dec = log_data.get("last_seen", {}).get("decision_cycle")
    if not last_dec:
        items.append(
            "No decision cycle has run in the last 7 days. Restart the app."
        )

    # Calibration
    overall = preds.get("overall") or {}
    if overall.get("n", 0) >= 8 and overall.get("in_range_pct", 100) < 50:
        items.append(
            f"Hit rate is only {overall['in_range_pct']}% over {overall['n']} "
            "predictions. Consider widening projection ranges or reviewing prompts."
        )
    if preds.get("alerts_fired", 0) > 10:
        items.append(
            f"{preds['alerts_fired']} alerts fired this week — high volume. "
            "Consider tightening the AI emergency-confirm threshold."
        )

    return items


# ------------------------------------------------------------------ runner

def run_weekly_audit() -> bool:
    log_data = _parse_log_window(WEEK_SECONDS)
    ai = _check_ai()
    feeds = _check_data_feeds()
    emails = _check_emails(log_data)
    preds = _check_predictions()
    actions = _build_action_items(log_data, ai, feeds, emails, preds)

    audit = {
        "ts": time.time(),
        "log": log_data,
        "ai": ai,
        "feeds": feeds,
        "emails": emails,
        "predictions": preds,
        "actions": actions,
    }
    state_set("weekly_audit", audit)
    return _send_audit_email(audit)


# ------------------------------------------------------------------ email

def _ok_or_warn(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def _send_audit_email(audit: dict) -> bool:
    today = datetime.now().strftime("%a %b %-d")
    counts = (audit.get("log") or {}).get("counts") or {}
    last_seen = (audit.get("log") or {}).get("last_seen") or {}
    ai = audit.get("ai") or {}
    feeds = audit.get("feeds") or {}
    emails = audit.get("emails") or {}
    preds = audit.get("predictions") or {}
    overall = preds.get("overall") or {}
    trend = preds.get("trend") or {}
    actions = audit.get("actions") or []

    # System bullets
    sched_ok = bool(last_seen.get("decision_cycle"))
    sys_bullets = [
        f"{_ok_or_warn(sched_ok)} Scheduler "
        f"{('running, last cycle ' + last_seen['decision_cycle']) if sched_ok else 'has not run in 7d'}",
        f"{_ok_or_warn(ai.get('online'))} AI "
        f"{(('online via ' + (ai.get('backend') or '?') + ' (' + (ai.get('model') or '?') + ')') if ai.get('online') else 'offline')}"
        + (f" · last latency {int(ai['last_latency_ms'])} ms" if ai.get("last_latency_ms") else ""),
        f"{counts.get('sentiment_polls',0)} sentiment polls · "
        f"{counts.get('decision_cycles',0)} decision cycles · "
        f"{counts.get('geo_polls',0)} geo polls",
        f"{counts.get('ai_failures',0)} AI failure(s), "
        f"{counts.get('errors',0)} error(s), "
        f"{counts.get('warnings',0)} warning(s)",
    ]

    # Predictions bullets
    pred_bullets: list[str] = []
    if overall.get("n", 0) > 0:
        pred_bullets.append(
            f"<strong>{overall['in_range_pct']}%</strong> in range "
            f"({overall['n']} predictions) · "
            f"<strong>{overall['direction_correct_pct']}%</strong> direction · "
            f"avg error <strong>{overall['avg_error_pct']}%</strong>"
        )
        if trend.get("trend") and trend["trend"] != "insufficient_data":
            arrow = (
                "📈" if trend["trend"] == "improving"
                else "📉" if trend["trend"] == "regressing"
                else "➡️"
            )
            pred_bullets.append(
                f"{arrow} {trend['trend'].title()}: "
                f"recent {trend['recent_in_range_pct']}% vs prior "
                f"{trend['prior_in_range_pct']}% (Δ {trend['delta_pct']:+}%)"
            )
    else:
        pred_bullets.append(
            "<span class='muted'>No scored predictions yet — first cycle pending.</span>"
        )
    pred_bullets.append(f"{preds.get('alerts_fired',0)} alert(s) fired this week")

    # Data feeds bullets
    healthy = feeds.get("tickers_healthy", 0)
    total = feeds.get("tickers_total", 0)
    feed_bullets = [
        f"{_ok_or_warn(healthy == total)} <strong>{healthy}/{total}</strong> "
        f"tickers returning live prices",
        f"{_ok_or_warn(feeds.get('newsapi_configured'))} NewsAPI "
        f"{'configured' if feeds.get('newsapi_configured') else 'not set'}",
        f"{_ok_or_warn(feeds.get('finnhub_configured'))} Finnhub "
        f"{'configured' if feeds.get('finnhub_configured') else 'not set'}",
    ]

    # Email bullets
    email_bullets = [
        f"{emails.get('successes_week',0)} sent · "
        f"{emails.get('failures_week',0)} failed",
        f"<span class='muted'>Last successful send:</span> "
        f"{emails.get('last_success') or '—'}",
    ]

    actions_html = (
        "".join(f"<li>{a}</li>" for a in actions)
        if actions
        else "<li>None this week ✓</li>"
    )

    def to_ul(items: list[str]) -> str:
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    html = f"""
<html><head>{_CSS}</head><body><div class="wrap">
  <h1>🩺 Weekly Health Report · {today}</h1>

  <div class="box">
    <h2>System</h2>
    {to_ul(sys_bullets)}
  </div>

  <div class="box">
    <h2>Predictions</h2>
    {to_ul(pred_bullets)}
  </div>

  <div class="box">
    <h2>Data Feeds</h2>
    {to_ul(feed_bullets)}
  </div>

  <div class="box">
    <h2>Emails</h2>
    {to_ul(email_bullets)}
  </div>

  <div class="box">
    <h2>Action Items</h2>
    <ul>{actions_html}</ul>
  </div>

  <div class="foot">{AI_DISCLAIMER}</div>
</div></body></html>
"""
    return _send(f"🩺 VigilantTrader · Weekly Health Report · {today}", html)
