"""Streamlit dashboard for VigilantTrader v3 AI Edition."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai_engine import ai_engine
from config import (
    AI_DISCLAIMER,
    MARKET_POLL_INTERVAL_MIN,
    NEWS_POLL_INTERVAL_MIN,
    TICKERS,
    TIMEZONE,
    email_configured,
)
from database import (
    get_conn,
    latest_ai_verdicts,
    recent_alerts,
    recent_divergences,
    state_age_seconds,
    state_get,
)
from accuracy_tracker import overall_accuracy, recent_accuracy, trend_snapshot
from data_fetcher import fetch_intraday
from decision_engine import run_decision_cycle
from friday_email import run_friday_recap
from health_audit import run_weekly_audit
from scheduler import start_scheduler
from sentiment_engine import run_geo_poll, run_sentiment_poll
from weekly_email import run_weekly_outlook


# ---------------------------------------------------------------- bootstrap

st.set_page_config(
    page_title="VigilantTrader AI",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Boot the scheduler exactly once for this Streamlit process.
if "_sched_started" not in st.session_state:
    start_scheduler(run_initial=True)
    st.session_state["_sched_started"] = True


# ---------------------------------------------------------------- helpers

BIAS_COLOR = {
    "Bullish": "#16a34a",
    "Bearish": "#dc2626",
    "Cautious": "#d97706",
    "Neutral": "#64748b",
}

URGENCY_COLOR = {
    "Critical": "#dc2626",
    "Alert": "#ea580c",
    "Watch": "#ca8a04",
    "Monitor": "#475569",
}


def _badge(text: str, color: str) -> str:
    return (
        f"<span style='background:{color};color:white;padding:3px 10px;"
        f"border-radius:999px;font-size:12px;font-weight:600;"
        f"margin-right:6px'>{text}</span>"
    )


def _ai_status_indicator() -> tuple[str, str]:
    online = ai_engine.is_online()
    s = ai_engine.status
    if online and s.backend == "ollama":
        dot = "🟢"
        msg = f"Ollama running ({s.model})"
    elif online and s.backend == "groq":
        dot = "🟡"
        msg = f"Using Groq fallback ({s.model})"
    else:
        dot = "🔴"
        msg = "AI offline — quant only"
    if s.last_latency_ms:
        msg += f" · {int(s.last_latency_ms)} ms"
    return dot, msg


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- header

st.markdown(
    "<h1 style='margin-bottom:0'>🛰️ VigilantTrader <span style='color:#94a3b8'>"
    "v3 · AI Edition</span></h1>",
    unsafe_allow_html=True,
)

dot, ai_msg = _ai_status_indicator()
top_l, top_r = st.columns([4, 2])
with top_l:
    st.caption(
        f"Tracking {len(TICKERS)} tickers · market poll {MARKET_POLL_INTERVAL_MIN} min · "
        f"news poll {NEWS_POLL_INTERVAL_MIN} min · timezone {TIMEZONE}"
    )
with top_r:
    st.markdown(
        f"<div style='text-align:right'><b>{dot}</b> {ai_msg}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Controls")
    st.write(f"Email configured: {'✅' if email_configured() else '⚠️ no SMTP creds'}")
    st.divider()
    if st.button("🔄 Run sentiment poll now", use_container_width=True):
        with st.spinner("Polling news + AI digest..."):
            run_sentiment_poll()
        st.success("Sentiment refreshed")
    if st.button("📈 Run decision cycle now", use_container_width=True):
        with st.spinner("Computing signals + AI verdicts..."):
            run_decision_cycle()
        st.success("Decisions refreshed")
    if st.button("🌐 Run geo poll now", use_container_width=True):
        with st.spinner("Polling geopolitical headlines..."):
            run_geo_poll()
        st.success("Geo refreshed")
    if st.button("📅 Send weekly outlook now", use_container_width=True):
        with st.spinner("Generating weekly outlook..."):
            ok = run_weekly_outlook()
        if ok:
            st.success("Sent ✅")
        else:
            st.warning("Send failed (check SMTP)")
    if st.button("📊 Send Friday recap now", use_container_width=True):
        with st.spinner("Scoring Monday's predictions..."):
            ok = run_friday_recap()
        if ok:
            st.success("Recap sent ✅")
        else:
            st.info("No Monday predictions to score yet (run weekly outlook first).")
    if st.button("🩺 Run health audit now", use_container_width=True):
        with st.spinner("Auditing system health..."):
            ok = run_weekly_audit()
        if ok:
            st.success("Audit emailed ✅")
        else:
            st.warning("Audit ran but email failed (check SMTP)")
    st.divider()
    st.caption(AI_DISCLAIMER)


# ---------------------------------------------------------------- tabs

tab_overview, tab_ai, tab_accuracy, tab_alerts = st.tabs(
    ["📊 Overview", "🧠 AI Digest", "📈 Accuracy", "🚨 Alerts"]
)


# =============================== OVERVIEW ============================

with tab_overview:
    verdicts: dict = state_get("verdicts") or {}
    sentiment: dict = state_get("sentiment_state") or {}
    weekly_payload = state_get("weekly_payload") or {}
    projections_state: dict = weekly_payload.get("projections") or {}

    if not verdicts:
        st.info(
            "No verdicts yet — initial cycle is running in the background. "
            "Click *Run decision cycle now* in the sidebar to force one."
        )

    cols = st.columns(2)
    for i, ticker in enumerate(TICKERS):
        v = verdicts.get(ticker, {})
        s = sentiment.get(ticker, {})
        proj = projections_state.get(ticker, {})
        with cols[i % 2]:
            with st.container(border=True):
                bias = v.get("bias", "Neutral")
                conf = v.get("ai_confidence", "—")
                urg = v.get("ai_urgency", "Monitor")
                price = v.get("price")
                chg = v.get("intraday_chg_pct")

                hdr = (
                    f"<h3 style='margin:0'>{ticker}"
                    f" <small style='color:#64748b'>"
                    f"{('$' + format(price, '.2f')) if price else ''}"
                    f" {('(' + format(chg, '+.2f') + '%)') if chg is not None else ''}"
                    f"</small></h3>"
                )
                st.markdown(hdr, unsafe_allow_html=True)

                # AI weekly projection (from latest Monday outlook)
                if proj and proj.get("target_low") and proj.get("target_high"):
                    move_low = proj.get("move_low_pct", 0)
                    move_high = proj.get("move_high_pct", 0)
                    move_exp = proj.get("move_expected_pct", 0)
                    direction = proj.get("direction", "Sideways")
                    proj_conf = proj.get("confidence", "—")
                    catalyst = proj.get("key_catalyst", "")
                    arrow = (
                        "↑" if direction == "Up"
                        else "↓" if direction == "Down"
                        else "→"
                    )
                    color = (
                        "#15803d" if direction == "Up"
                        else "#b91c1c" if direction == "Down"
                        else "#64748b"
                    )
                    proj_html = (
                        f"<div style='margin:6px 0 8px 0; padding:8px 10px;"
                        f"background:#f1f5f9; border-left:3px solid {color};"
                        f"border-radius:6px; font-size:13px'>"
                        f"<b style='color:{color}'>{arrow} 5-day target</b> "
                        f"<span style='color:#0f172a'>"
                        f"${proj['target_low']:.2f} – ${proj['target_high']:.2f}</span> "
                        f"<span style='color:#64748b'>"
                        f"({move_low:+.1f}% to {move_high:+.1f}%)</span><br>"
                        f"<span style='color:#475569'>Expected close </span>"
                        f"<b>${proj['expected_close']:.2f}</b> "
                        f"<span style='color:#64748b'>({move_exp:+.1f}%)</span> · "
                        f"<span style='color:#64748b'>conf</span> {proj_conf}"
                        + (
                            f"<br><span style='color:#475569;font-size:12px'>"
                            f"Catalyst: {catalyst}</span>"
                            if catalyst else ""
                        )
                        + "</div>"
                    )
                    st.markdown(proj_html, unsafe_allow_html=True)
                else:
                    st.markdown(
                        "<div style='margin:6px 0 8px 0; padding:6px 10px;"
                        "background:#f1f5f9; border-left:3px solid #cbd5e1;"
                        "border-radius:6px; font-size:12px; color:#64748b'>"
                        "5-day target: <i>not yet generated. "
                        "Run weekly outlook in the sidebar.</i>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                badges = (
                    _badge(f"Bias: {bias}", BIAS_COLOR.get(bias, "#64748b"))
                    + _badge(f"Conf: {conf}", "#475569")
                    + _badge(f"Urgency: {urg}", URGENCY_COLOR.get(urg, "#475569"))
                )
                st.markdown(badges, unsafe_allow_html=True)

                meta = (
                    f"RSI **{v.get('rsi','—')}** · Crossover **{v.get('ema_crossover','—')}** "
                    f"· Pattern **{v.get('pattern','—')}** · Score **{v.get('score','—')}**"
                )
                st.caption(meta)

                themes = v.get("ai_themes") or []
                if themes:
                    st.markdown(
                        " ".join(
                            f"<span style='background:#1e293b;color:#cbd5e1;"
                            f"padding:2px 8px;border-radius:8px;font-size:11px;"
                            f"margin-right:4px'>{t}</span>"
                            for t in themes[:5]
                        ),
                        unsafe_allow_html=True,
                    )

                with st.expander("AI reasoning"):
                    st.write(v.get("ai_reasoning") or "—")
                    risks = v.get("ai_risk_factors") or []
                    if risks:
                        st.markdown("**Risk factors**")
                        for r in risks:
                            st.markdown(f"- {r}")
                    st.markdown(
                        f"_Recommended action:_ **{v.get('ai_action') or '—'}**"
                    )
                    if v.get("divergence_note"):
                        st.warning(v["divergence_note"])
                    st.caption(AI_DISCLAIMER)

                # Mini price chart
                df = fetch_intraday(ticker, period="2d", interval="15m")
                if not df.empty:
                    fig = go.Figure(
                        data=[
                            go.Candlestick(
                                x=df.index,
                                open=df["open"],
                                high=df["high"],
                                low=df["low"],
                                close=df["close"],
                                increasing_line_color="#16a34a",
                                decreasing_line_color="#dc2626",
                            )
                        ]
                    )
                    fig.update_layout(
                        height=220,
                        margin=dict(l=0, r=0, t=0, b=0),
                        xaxis_rangeslider_visible=False,
                        template="plotly_dark",
                    )
                    st.plotly_chart(fig, use_container_width=True)


# =============================== AI DIGEST ===========================

with tab_ai:
    st.subheader("🧠 AI Digest")

    age = state_age_seconds("verdicts")
    age_label = (
        f"{int(age)} sec ago" if age is not None and age < 120
        else (f"{int(age/60)} min ago" if age else "—")
    )
    st.caption(f"Last AI analysis: {age_label}")

    # Risk meter
    verdicts = state_get("verdicts") or {}
    if verdicts:
        risk_map = {"Low": 25, "Medium": 50, "High": 75, "Critical": 95}
        risks = [
            risk_map.get(v.get("ai_risk_level", "Medium"), 50)
            for v in verdicts.values()
        ]
        global_risk = round(sum(risks) / len(risks)) if risks else 0
        gauge = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=global_risk,
                title={"text": "Global AI Risk"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#ea580c"},
                    "steps": [
                        {"range": [0, 33], "color": "#14532d"},
                        {"range": [33, 66], "color": "#78350f"},
                        {"range": [66, 100], "color": "#7f1d1d"},
                    ],
                },
            )
        )
        gauge.update_layout(height=240, template="plotly_dark",
                            margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(gauge, use_container_width=True)

    # Weekly focus
    weekly = (state_get("weekly_payload") or {}).get("weekly_focus")
    if weekly:
        with st.container(border=True):
            st.markdown("### AI Weekly Focus")
            st.write(weekly)
    else:
        st.info(
            "AI Weekly Focus is generated each Monday morning (or via the sidebar "
            "*Send weekly outlook* button)."
        )

    # Per-ticker AI summaries
    st.markdown("### Per-ticker AI summaries")
    for t, v in verdicts.items():
        with st.container(border=True):
            bias = v.get("bias", "Neutral")
            st.markdown(
                f"**{t}** "
                + _badge(bias, BIAS_COLOR.get(bias, "#64748b"))
                + _badge(f"Risk {v.get('ai_risk_level','—')}", "#475569"),
                unsafe_allow_html=True,
            )
            st.write(v.get("ai_summary") or v.get("ai_reasoning") or "—")
            themes = v.get("ai_themes") or []
            if themes:
                st.markdown(
                    " ".join(
                        f"<span style='background:#1e293b;color:#cbd5e1;"
                        f"padding:2px 8px;border-radius:8px;font-size:11px;"
                        f"margin-right:4px'>{th}</span>"
                        for th in themes[:6]
                    ),
                    unsafe_allow_html=True,
                )

    # Divergence log
    st.markdown("### AI vs Quant divergence (last 5)")
    divs = recent_divergences(limit=5)
    if not divs:
        st.caption("No divergences logged.")
    else:
        df = pd.DataFrame(
            [
                {
                    "When": _fmt_ts(d["ts"]),
                    "Ticker": d["ticker"],
                    "Quant": d["quant_bias"],
                    "AI": d["ai_bias"],
                    "Note": d["note"],
                }
                for d in divs
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.caption(AI_DISCLAIMER)


# =============================== ACCURACY ===========================

with tab_accuracy:
    st.subheader("📈 Prediction Accuracy")
    st.caption(
        "How AI weekly projections have performed vs. actual Friday closes. "
        "Updated automatically each Friday at 16:30 local."
    )

    overall = overall_accuracy(n=8)
    trend = trend_snapshot(window=4)

    if overall.get("n", 0) == 0:
        st.info(
            "No scored predictions yet. The first batch will appear after one "
            "Monday → Friday cycle. Use the sidebar buttons to fast-track it."
        )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Predictions scored", overall["n"])
        c2.metric("Inside range", f"{overall['in_range_pct']}%")
        c3.metric("Direction correct", f"{overall['direction_correct_pct']}%")
        c4.metric("Avg error", f"{overall['avg_error_pct']}%")

        if trend.get("trend") and trend["trend"] != "insufficient_data":
            arrow = (
                "📈" if trend["trend"] == "improving"
                else "📉" if trend["trend"] == "regressing"
                else "➡️"
            )
            st.markdown(
                f"### {arrow} Trend: **{trend['trend'].title()}**  "
                f"<span style='color:#94a3b8'>"
                f"recent {trend['recent_in_range_pct']}% vs prior "
                f"{trend['prior_in_range_pct']}% "
                f"({trend['delta_pct']:+}%)</span>",
                unsafe_allow_html=True,
            )

        st.markdown("### Per-ticker accuracy (last 8 weeks)")
        per_ticker_rows = []
        for ticker in TICKERS:
            s = recent_accuracy(ticker, n=8)
            if s.get("n", 0) == 0:
                continue
            per_ticker_rows.append({
                "Ticker": ticker,
                "Scored": s["n"],
                "In range": f"{s['in_range']}/{s['n']}",
                "Dir correct": f"{s['direction_correct']}/{s['n']}",
                "Avg error %": s["avg_error_pct"],
                "Calibration": (
                    "Too conservative" if s["bias_drift_pct"] > 1.5
                    else "Too optimistic" if s["bias_drift_pct"] < -1.5
                    else "Well-calibrated"
                ),
            })
        if per_ticker_rows:
            st.dataframe(
                pd.DataFrame(per_ticker_rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No per-ticker data yet.")

        st.markdown("### Recent predictions")
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT ticker, monday_ts, monday_price, target_low, target_high,
                       expected_close, friday_close, actual_move_pct,
                       expected_error_pct, in_range, direction_correct
                FROM weekly_predictions
                ORDER BY monday_ts DESC LIMIT 30
                """
            ).fetchall()
        if rows:
            recent_df = pd.DataFrame([dict(r) for r in rows])
            recent_df["Monday"] = pd.to_datetime(
                recent_df["monday_ts"], unit="s"
            ).dt.strftime("%Y-%m-%d")
            display_df = recent_df[[
                "Monday", "ticker", "monday_price", "target_low", "target_high",
                "expected_close", "friday_close", "actual_move_pct",
                "expected_error_pct", "in_range", "direction_correct",
            ]].rename(columns={
                "ticker": "Ticker",
                "monday_price": "Mon $",
                "target_low": "Low",
                "target_high": "High",
                "expected_close": "Expected",
                "friday_close": "Fri $",
                "actual_move_pct": "Move %",
                "expected_error_pct": "Error %",
                "in_range": "In rng",
                "direction_correct": "Dir ✓",
            })
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No predictions logged yet.")

    st.caption(AI_DISCLAIMER)


# =============================== ALERTS ==============================

with tab_alerts:
    st.subheader("🚨 Recent alerts")
    alerts = recent_alerts(limit=50)
    if not alerts:
        st.info("No alerts fired yet.")
    else:
        df = pd.DataFrame(
            [
                {
                    "When": _fmt_ts(a["ts"]),
                    "Ticker": a.get("ticker") or "—",
                    "Severity": a.get("severity") or "—",
                    "Kind": a.get("kind") or "—",
                    "Headline": a.get("headline") or "",
                }
                for a in alerts
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    geo = state_get("geo_state") or {}
    if geo.get("headlines"):
        st.markdown("### Latest macro headlines")
        for h in geo["headlines"][:10]:
            url = h.get("url") or "#"
            st.markdown(f"- [{h['headline']}]({url}) — *{h.get('source','')}*")
    st.caption(AI_DISCLAIMER)
