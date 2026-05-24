"""First-Sunday-of-month accuracy report email."""
from __future__ import annotations

from accuracy_tracker import monthly_report_data
from config import log
from email_system import send_monthly_report


def run_monthly_report() -> None:
    log.info("Running monthly accuracy report")
    data = monthly_report_data(months_back=1)
    sent = send_monthly_report(data)
    log.info("Monthly report email %s (signals: %d)", "sent" if sent else "failed", data.get("total_signals", 0))
