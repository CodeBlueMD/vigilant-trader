"""Friday recap email — compares Monday's projections to Friday's actual close
and computes accuracy metrics. Closes the feedback loop for self-calibration."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from accuracy_tracker import evaluate_friday, overall_accuracy, trend_snapshot
from config import AI_DISCLAIMER, TICKERS, log
from data_fetcher import latest_quote
from email_system import _CSS, _bias_class, _fmt_pct, _fmt_price, _move_class, _send


def _fetch_current_prices() -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for ticker in TICKERS:
        try:
            q = latest_quote(ticker)
            out[ticker] = q.get("price")
        except Exception as e:  # noqa: BLE001
            log.warning("Friday price fetch failed for %s: %s", ticker, e)
            out[ticker] = None
    return out


def run_friday_recap() -> bool:
    prices = _fetch_current_prices()
    results = evaluate_friday(prices)
    if not results:
        log.info("Friday recap skipped — no Monday predictions to evaluate.")
        return False
    overall = overall_accuracy(n=8)
    trend = trend_snapshot(window=4)
    return _send_recap_email(results, overall, trend)


def _send_recap_email(
    results: list[dict],
    overall: dict,
    trend: dict,
) -> bool:
    today = datetime.now().strftime("%a %b %-d")

    rows_html = []
    in_range_count = sum(1 for r in results if r["in_range"])
    dir_correct_count = sum(1 for r in results if r["direction_correct"])
    avg_err = (
        sum(r["expected_error_pct"] for r in results) / len(results) if results else 0
    )

    for r in results:
        ticker = r["ticker"]
        bias_class = _bias_class("Bullish" if r["actual_move_pct"] > 0 else "Bearish")
        check_range = "✅" if r["in_range"] else "❌"
        check_dir = "✅" if r["direction_correct"] else "❌"
        bullets = [
            f"Predicted {_fmt_price(r['target_low'])}–{_fmt_price(r['target_high'])} "
            f"<span class='muted'>(expected {_fmt_price(r['expected_close'])})</span>",
            f"Actual close {_fmt_price(r['friday_close'])} "
            f"<span class='{_move_class(r['actual_move_pct'])}'>"
            f"({_fmt_pct(r['actual_move_pct'])} from Mon)</span>",
            f"{check_range} In range · {check_dir} Direction · "
            f"<span class='muted'>error {r['expected_error_pct']}%</span>",
        ]
        if r.get("key_catalyst"):
            bullets.append(
                f"<span class='muted'>Catalyst was:</span> {r['key_catalyst']}"
            )
        bullets_html = "".join(f"<li>{b}</li>" for b in bullets)
        rows_html.append(f"""
        <div class="ticker-row">
          <div class="row">
            <span class="ticker-name">{ticker}</span>
            <span class="badge {bias_class}">
              {'Up' if r['actual_move_pct'] > 0 else 'Down'}
            </span>
            <span class="badge neutral">Conf: {r.get('confidence','—')}</span>
          </div>
          <ul>{bullets_html}</ul>
        </div>""")

    summary_bullets = [
        f"<strong>{in_range_count}/{len(results)}</strong> inside predicted range",
        f"<strong>{dir_correct_count}/{len(results)}</strong> direction correct",
        f"Average error from expected close: <strong>{avg_err:.1f}%</strong>",
    ]

    overall_bullets = []
    if overall.get("n", 0) > 0:
        overall_bullets = [
            f"All-time hit rate: <strong>{overall['in_range_pct']}%</strong> "
            f"in range over {overall['n']} predictions",
            f"All-time direction accuracy: <strong>{overall['direction_correct_pct']}%</strong>",
            f"All-time avg error: <strong>{overall['avg_error_pct']}%</strong>",
        ]

    trend_line = ""
    if trend.get("trend") and trend["trend"] != "insufficient_data":
        arrow = (
            "📈" if trend["trend"] == "improving"
            else "📉" if trend["trend"] == "regressing"
            else "➡️"
        )
        trend_line = (
            f"{arrow} <strong>{trend['trend'].title()}</strong>: last 4 weeks "
            f"{trend['recent_in_range_pct']}% in range vs prior "
            f"{trend['prior_in_range_pct']}% (Δ {trend['delta_pct']:+}%)"
        )

    summary_html = "".join(f"<li>{b}</li>" for b in summary_bullets)
    overall_html = "".join(f"<li>{b}</li>" for b in overall_bullets)

    html = f"""
<html><head>{_CSS}</head><body><div class="wrap">
  <h1>📊 Friday Recap · {today}</h1>

  <div class="box">
    <h2>This Week</h2>
    <ul>{summary_html}</ul>
    {f'<div class="row" style="margin-top:8px">{trend_line}</div>' if trend_line else ''}
  </div>

  <div class="box">
    <h2>📈 Per-Ticker</h2>
    {''.join(rows_html)}
  </div>

  {f'<div class="box"><h2>📉 All-Time</h2><ul>{overall_html}</ul></div>' if overall_bullets else ''}

  <div class="foot">
    {AI_DISCLAIMER} · Predictions are probabilistic, recap is for calibration only.
  </div>
</div></body></html>
"""
    return _send(f"📊 VigilantTrader · Friday Recap · {today}", html)
