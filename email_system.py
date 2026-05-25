"""SMTP sender + mobile-first email templates for VigilantTrader positional alerts."""
from __future__ import annotations

import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from config import (
    AI_DISCLAIMER,
    ALERT_RECIPIENT,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    email_configured,
    log,
)


def _send(subject: str, html: str) -> bool:
    if not email_configured():
        log.warning("Email skipped — SMTP not configured.")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_RECIPIENT
    msg.set_content(re.sub(r"<[^>]+>", "", html))
    msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        log.info("Email sent: %s", subject)
        return True
    except Exception as e:
        log.error("Email failed: %s", e)
        return False


_CSS = """
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#fff;color:#111827;margin:0;padding:16px;font-size:15px;line-height:1.5}
.wrap{max-width:560px;margin:0 auto}
.box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;margin:10px 0}
h1{font-size:20px;margin:0 0 6px;color:#0f172a}
h2{font-size:11px;margin:0 0 8px;color:#475569;letter-spacing:.06em;text-transform:uppercase}
.row{margin:4px 0;color:#111827}
.label{color:#475569;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-right:6px}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;margin-right:4px}
.bull{background:#dcfce7;color:#14532d;border:1px solid #86efac}
.bear{background:#fee2e2;color:#7f1d1d;border:1px solid #fca5a5}
.med{background:#fef9c3;color:#713f12;border:1px solid #fde047}
.neutral{background:#e2e8f0;color:#1e293b;border:1px solid #cbd5e1}
.holding{background:#ede9fe;color:#3b0764;border:1px solid #c4b5fd}
.gate-pass{color:#15803d;font-size:12px}
.gate-fail{color:#b91c1c;font-size:12px}
.size-box{background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:10px 14px;margin:8px 0}
.foot{font-size:11px;color:#64748b;margin-top:14px;padding:8px 0;border-top:1px solid #e2e8f0}
table{width:100%;border-collapse:collapse}
td{padding:5px 4px;font-size:13px;vertical-align:top}
th{padding:5px 4px;font-size:11px;color:#475569;text-transform:uppercase;
   letter-spacing:.05em;text-align:left;border-bottom:1px solid #e2e8f0}
.up{color:#15803d;font-weight:600}
.down{color:#b91c1c;font-weight:600}
.flat{color:#475569}
</style>
"""


def _bias_class(signal_type: str | None, confidence: str | None = None) -> str:
    if signal_type == "bullish":
        return "bull" if confidence == "High" else "med"
    if signal_type == "bearish":
        return "bear"
    return "neutral"


def _fmt_price(p: Any, currency: str = "USD") -> str:
    try:
        sym = "CA$" if currency == "CAD" else "$"
        return f"{sym}{float(p):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(p: Any) -> str:
    try:
        v = float(p)
        return f"{'+'if v>=0 else''}{v:.1f}%"
    except (TypeError, ValueError):
        return "—"


def send_positional_alert(result: Any) -> bool:
    sig = result.signals
    signal_type = result.signal_type or "unknown"
    confidence = result.confidence or "Medium"
    ticker = result.ticker
    price = result.price
    currency = result.currency
    today = datetime.now().strftime("%b %-d, %Y")

    badge_class = _bias_class(signal_type, confidence)
    holding_badge = '<span class="badge holding">HOLDING</span>' if result.is_holding else ""

    gate_rows = "".join(
        f'<tr><td class="{"gate-pass" if g.passed else "gate-fail"}">'
        f'{"✓" if g.passed else "✗"} {g.name.replace("_"," ").title()}</td>'
        f'<td class="flat" style="font-size:12px">{g.detail}</td></tr>'
        for g in result.gates
    )

    sizing_html = ""
    if result.suggested_position_usd and not result.is_holding:
        stop_pct = sig.stop_distance_pct if sig else None
        sizing_html = (
            f'<div class="size-box">'
            f'<span class="label">Suggested position</span><strong>${result.suggested_position_usd:,.0f} USD</strong>'
            + (f'<span class="label" style="margin-left:12px">Stop distance</span><strong>{stop_pct:.1f}% (2x ATR)</strong>' if stop_pct else "")
            + "</div>"
        )

    earnings_html = (
        f'<div class="row" style="color:#92400e">⚠ Earnings: {result.earnings_date}</div>'
        if result.earnings_date else ""
    )

    factors_html = "".join(
        f'<div class="row" style="font-size:13px">· {f}</div>'
        for f in result.confluence_factors
    )

    html = f"""
<html><head>{_CSS}</head><body><div class="wrap">
  <h1>{ticker} · {_fmt_price(price, currency)}</h1>
  <div class="row">
    <span class="badge {badge_class}">{signal_type.upper()}</span>
    <span class="badge neutral">Confidence: {confidence}</span>
    {holding_badge}
    <span class="flat" style="font-size:12px">{today}</span>
  </div>

  <div class="box">
    <h2>Confluence Signals</h2>
    {factors_html or '<div class="flat">—</div>'}
  </div>

  {sizing_html}
  {earnings_html}

  <div class="box">
    <h2>Gate Results</h2>
    <table>{gate_rows}</table>
  </div>

  <div class="foot">{AI_DISCLAIMER}</div>
</div></body></html>"""

    subject = f"[{confidence.upper()}] {ticker} {signal_type.upper()} · {_fmt_price(price, currency)}"
    return _send(subject, html)


def send_weekly_summary(results: list, narrative: str) -> bool:
    today = datetime.now().strftime("%a %b %-d, %Y")

    rows_html = ""
    for r in results:
        sig = r.signals
        if not sig:
            continue
        trend_class = "up" if sig.weekly_trend == "up" else "down" if sig.weekly_trend == "down" else "flat"
        rsi_val = f"{sig.rsi_21:.0f}" if sig.rsi_21 else "—"
        rs_text = (
            f"{_fmt_pct(sig.return_63d)} vs SPY {_fmt_pct(sig.spy_return_63d)}"
            if sig.return_63d is not None and sig.spy_return_63d is not None
            else "—"
        )
        if r.signal_type:
            status = f'<span class="badge {_bias_class(r.signal_type, r.confidence)}">{r.signal_type.upper()} ({r.confidence})</span>'
        else:
            short = r.not_confirmed_reason.split("—")[-1].strip()[:40] if r.not_confirmed_reason else "Watching"
            status = f'<span class="flat" style="font-size:12px">{short}</span>'

        rows_html += (
            f"<tr><td><strong>{r.ticker}{'*' if r.is_holding else ''}</strong></td>"
            f"<td><span class='{trend_class}'>{sig.weekly_trend}</span></td>"
            f"<td>{_fmt_price(sig.price, sig.currency)}</td>"
            f"<td>{rsi_val}</td>"
            f"<td style='font-size:12px'>{rs_text}</td>"
            f"<td>{status}</td></tr>"
        )

    html = f"""
<html><head>{_CSS}</head><body><div class="wrap">
  <h1>Weekly Positional Summary · {today}</h1>
  <div class="box"><div class="narrative">{narrative}</div></div>
  <div class="box">
    <h2>Watchlist Status (* = holding)</h2>
    <table>
      <tr><th>Ticker</th><th>W1 Trend</th><th>Price</th><th>RSI(21)</th><th>63d RS</th><th>Status</th></tr>
      {rows_html}
    </table>
  </div>
  <div class="foot">{AI_DISCLAIMER}</div>
</div></body></html>"""

    return _send(f"Weekly Summary · {today}", html)


def send_monthly_report(data: dict) -> bool:
    today = datetime.now().strftime("%B %Y")

    if data.get("total_signals", 0) == 0:
        html = f"""
<html><head>{_CSS}</head><body><div class="wrap">
  <h1>Monthly Report · {today}</h1>
  <div class="box"><div class="row">No signals fired in the past month.</div></div>
  <div class="foot">{AI_DISCLAIMER}</div>
</div></body></html>"""
        return _send(f"Monthly Accuracy Report · {today}", html)

    wr_30 = f"{data['win_rate_30d_pct']:.0f}%" if data.get("win_rate_30d_pct") is not None else "pending"
    wr_60 = f"{data['win_rate_60d_pct']:.0f}%" if data.get("win_rate_60d_pct") is not None else "pending"

    conf_rows = "".join(
        f"<tr><td>{conf}</td><td>{d['wins']}/{d['total']}</td>"
        f"<td>{round(d['wins']/d['total']*100) if d['total'] else 0}%</td></tr>"
        for conf, d in data.get("by_confidence", {}).items()
    )

    ticker_rows = "".join(
        f"<tr><td><strong>{t['ticker']}</strong></td><td>{t['wins']}/{t['total']}</td>"
        f"<td>{t['win_rate_pct']}%</td>"
        f"<td class=\"{'up' if t['avg_return_pct']>0 else 'down'}\">{_fmt_pct(t['avg_return_pct'])}</td></tr>"
        for t in data.get("by_ticker", [])
    )

    html = f"""
<html><head>{_CSS}</head><body><div class="wrap">
  <h1>Monthly Accuracy Report · {today}</h1>
  <div class="box">
    <h2>Overview</h2>
    <div class="row"><span class="label">Signals fired</span><strong>{data['total_signals']}</strong></div>
    <div class="row"><span class="label">30-day win rate</span><strong>{wr_30}</strong>
      <span class="flat" style="font-size:12px">({data.get('evaluated_30d',0)} evaluated)</span></div>
    <div class="row"><span class="label">60-day win rate</span><strong>{wr_60}</strong>
      <span class="flat" style="font-size:12px">({data.get('evaluated_60d',0)} evaluated)</span></div>
    <div class="row"><span class="label">Pending</span><strong>{data.get('pending_evaluation',0)}</strong></div>
  </div>
  <div class="box">
    <h2>By Confidence Level</h2>
    <table><tr><th>Confidence</th><th>W/T</th><th>Win Rate</th></tr>
    {conf_rows or '<tr><td colspan="3">No evaluated signals yet</td></tr>'}
    </table>
  </div>
  <div class="box">
    <h2>By Ticker (30d)</h2>
    <table><tr><th>Ticker</th><th>W/T</th><th>Win Rate</th><th>Avg Return</th></tr>
    {ticker_rows or '<tr><td colspan="4">No evaluated signals yet</td></tr>'}
    </table>
  </div>
  <div class="foot">{AI_DISCLAIMER}</div>
</div></body></html>"""

    return _send(f"Monthly Accuracy Report · {today}", html)
