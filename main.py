"""VigilantTrader — headless daemon entry point.

Run: python main.py
Keeps running, scheduler handles all timed jobs.
"""
from __future__ import annotations

import time

from config import log
from database import init_db
from scheduler import start_scheduler


def main() -> None:
    log.info("VigilantTrader Positional Edition starting...")
    init_db()
    start_scheduler()
    log.info("Scheduler running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("VigilantTrader stopped.")


if __name__ == "__main__":
    main()
