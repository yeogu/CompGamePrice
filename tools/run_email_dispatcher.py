#!/usr/bin/env python3
"""Continuously deliver queued emails when SMTP is configured."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import sqlite3
import time

import dispatch_notification_outbox


running = True


def stop(_signal_number: int, _frame: object) -> None:
    global running
    running = False


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def dispatch_once(database: Path) -> tuple[int, int]:
    try:
        return dispatch_notification_outbox.dispatch(database, None)
    except sqlite3.OperationalError as error:
        if "locked" not in str(error).casefold():
            raise
        print(
            "Email dispatcher: database is busy; retrying on the next interval.",
            flush=True,
        )
        return 0, 0


def main() -> int:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    database = Path(
        os.environ.get("GAME_PRICE_DATABASE_PATH", "/data/game_prices.db")
    )
    interval = max(5, int(os.environ.get("EMAIL_DISPATCH_INTERVAL_SECONDS", "30")))
    warned = False
    while running:
        if not smtp_configured():
            if not warned:
                print("Email dispatcher is waiting for SMTP_HOST and SMTP_FROM.", flush=True)
                warned = True
        elif database.exists():
            warned = False
            sent, failed = dispatch_once(database)
            if sent or failed:
                print(f"Email dispatcher: sent={sent} failed={failed}", flush=True)
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
