"""APScheduler wiring for VigilantTrader positional edition.

Schedule:
  Weekdays 4:15 PM ET  — positional analysis + alerts on confirmed signals
  Daily    5:00 AM ET  — evaluate open signal outcomes (30d/60d)
  Sunday   8:00 AM ET  — weekly summary + monthly report (first Sunday only)
"""
from __future__ import annotations

import datetime
import threading
import time

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from accuracy_tracker import evaluate_open_signals, log_signal
from config import ANALYSIS_HOUR, ANALYSIS_MINUTE, TIMEZONE, log
from drawdown_monitor import check_holdings_drawdown
from email_system import send_drawdown_alert, send_positional_alert
from monthly_report import run_monthly_report
from positional_analyst import run_analysis_cycle
from weekly_summary import run_weekly_summary

_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None
_started = False


def _run_analysis() -> None:
    tz = pytz.timezone(TIMEZONE)
    if datetime.datetime.now(tz).weekday() >= 5:  # 5=Sat, 6=Sun
        log.info("Skipping analysis — weekend (APScheduler guard).")
        return
    if not _lock.acquire(blocking=False):
        log.info("Analysis already running — skipped.")
        return
    try:
        results = run_analysis_cycle()
        for result in results:
            if not result.signal_type:
                continue
            if result.confidence != "High":
                continue
            log_signal(
                ticker=result.ticker,
                signal_type=result.signal_type,
                confidence=result.confidence or "High",
                entry_price=result.price or 0,
                gates=result.gates,
                atr_stop=result.atr_stop,
                suggested_position_usd=result.suggested_position_usd,
                ai_narrative="",
            )
            send_positional_alert(result)
        _run_drawdown_check()
    except Exception as e:
        log.exception("Analysis cycle failed: %s", e)
    finally:
        _lock.release()


def _run_evaluations() -> None:
    try:
        n = evaluate_open_signals()
        if n:
            log.info("Evaluated %d open signal(s)", n)
    except Exception as e:
        log.exception("Signal evaluation failed: %s", e)


def _run_drawdown_check(tickers: list[str] | None = None) -> None:
    tz = pytz.timezone(TIMEZONE)
    if datetime.datetime.now(tz).weekday() >= 5:
        return
    try:
        alerts = check_holdings_drawdown(tickers)
        for alert in alerts:
            send_drawdown_alert(alert)
    except Exception as e:
        log.exception("Drawdown check failed: %s", e)


def _run_ibit_monday() -> None:
    _run_drawdown_check(["IBIT"])


def _run_sunday() -> None:
    run_weekly_summary()
    if datetime.date.today().day <= 7:
        run_monthly_report()


def start_scheduler(run_initial: bool = False) -> BackgroundScheduler:
    global _scheduler, _started
    if _started and _scheduler:
        return _scheduler

    tz = pytz.timezone(TIMEZONE)
    sched = BackgroundScheduler(timezone=tz)

    sched.add_job(
        _run_analysis,
        CronTrigger(day_of_week="mon-fri", hour=ANALYSIS_HOUR, minute=ANALYSIS_MINUTE, timezone=tz),
        id="analysis_cycle", replace_existing=True, max_instances=1, coalesce=True,
    )
    sched.add_job(
        _run_evaluations,
        CronTrigger(hour=5, minute=0, timezone=tz),
        id="evaluations", replace_existing=True,
    )
    sched.add_job(
        _run_sunday,
        CronTrigger(day_of_week="sun", hour=8, minute=0, timezone=tz),
        id="sunday_emails", replace_existing=True,
    )
    sched.add_job(
        _run_ibit_monday,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=tz),
        id="ibit_monday_check", replace_existing=True,
    )

    sched.start()
    _scheduler = sched
    _started = True
    log.info(
        "Scheduler started — analysis weekdays %02d:%02d, drawdown check same time, evals 05:00, Sunday 08:00, IBIT Monday 08:00 (%s)",
        ANALYSIS_HOUR, ANALYSIS_MINUTE, TIMEZONE,
    )

    if run_initial:
        threading.Thread(target=_run_analysis, daemon=True).start()

    return sched


if __name__ == "__main__":
    start_scheduler(run_initial=True)
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        if _scheduler:
            _scheduler.shutdown()
