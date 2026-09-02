#!/usr/bin/env python3
"""Create verified DealQuest backups periodically with retention."""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import signal
import sys

import database_backup
import periodic_job_status


MINIMUM_INTERVAL_SECONDS = 3600
stop_requested = False


def request_stop(signum: int, frame: object) -> None:
    del signum
    del frame
    global stop_requested
    stop_requested = True


def run_backup(
    database: Path,
    catalog: Path,
    output_directory: Path,
    retention_days: int,
    status_path: Path,
) -> bool:
    started_at = periodic_job_status.timestamp()
    periodic_job_status.write_status(
        status_path,
        {
            "job": "backup",
            "enabled": True,
            "status": "RUNNING",
            "lastStartedAt": started_at,
            "lastFinishedAt": None,
            "lastBackup": None,
            "removedFiles": 0,
            "error": None,
        },
    )
    try:
        backup, removed = database_backup.create_backup(
            database,
            output_directory,
            retention_days,
            catalog=catalog,
        )
    except Exception as error:
        periodic_job_status.write_status(
            status_path,
            {
                "job": "backup",
                "enabled": True,
                "status": "FAILED",
                "lastStartedAt": started_at,
                "lastFinishedAt": periodic_job_status.timestamp(),
                "lastBackup": None,
                "removedFiles": 0,
                "error": str(error),
            },
        )
        print(f"Automatic backup failed: {error}", file=sys.stderr, flush=True)
        return False
    periodic_job_status.write_status(
        status_path,
        {
            "job": "backup",
            "enabled": True,
            "status": "SUCCEEDED",
            "lastStartedAt": started_at,
            "lastFinishedAt": periodic_job_status.timestamp(),
            "lastBackup": backup.name,
            "removedFiles": removed,
            "error": None,
        },
    )
    print(f"Automatic backup created: {backup}", flush=True)
    return True


def run_scheduler(
    database: Path,
    catalog: Path,
    output_directory: Path,
    lock_path: Path,
    status_path: Path,
    interval_seconds: int,
    initial_delay_seconds: int,
    retention_days: int,
    single_run: bool,
) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    periodic_job_status.wait_with_heartbeat(
        initial_delay_seconds,
        lambda: stop_requested,
        status_path,
        "backup",
    )
    while not stop_requested:
        lock_busy = False
        succeeded = False
        with lock_path.open("w", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock_busy = True
            if lock_busy:
                print(f"Backup is already running: {lock_path}", file=sys.stderr)
            else:
                succeeded = run_backup(
                    database,
                    catalog,
                    output_directory,
                    retention_days,
                    status_path,
                )
        if single_run:
            if lock_busy:
                return 2
            return 0 if succeeded else 1
        current = periodic_job_status.read_status(status_path, "backup")
        periodic_job_status.write_status(
            status_path,
            {
                **current,
                "nextRunAt": periodic_job_status.future_timestamp(interval_seconds),
            },
        )
        periodic_job_status.wait_with_heartbeat(
            interval_seconds,
            lambda: stop_requested,
            status_path,
            "backup",
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.environ.get("GAME_PRICE_DATABASE_PATH", "/data/game_prices.db"), type=Path)
    parser.add_argument("--catalog", default=os.environ.get("GAME_PRICE_CATALOG_PATH", "/data/game_catalog.json"), type=Path)
    parser.add_argument("--output-dir", default=os.environ.get("BACKUP_OUTPUT_PATH", "/backups"), type=Path)
    parser.add_argument("--lock-file", default=os.environ.get("BACKUP_LOCK_PATH", "/tmp/dealquest-backup.lock"), type=Path)
    parser.add_argument("--status-file", default=os.environ.get("BACKUP_STATUS_PATH", "/tmp/dealquest-backup-status.json"), type=Path)
    parser.add_argument("--interval-seconds", default=os.environ.get("BACKUP_INTERVAL_SECONDS", "86400"))
    parser.add_argument("--initial-delay-seconds", default=os.environ.get("BACKUP_INITIAL_DELAY_SECONDS", "300"))
    parser.add_argument("--retention-days", default=os.environ.get("BACKUP_RETENTION_DAYS", "14"))
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    try:
        interval_seconds = periodic_job_status.parse_integer(arguments.interval_seconds, "interval-seconds", MINIMUM_INTERVAL_SECONDS)
        initial_delay_seconds = periodic_job_status.parse_integer(arguments.initial_delay_seconds, "initial-delay-seconds")
        retention_days = periodic_job_status.parse_integer(arguments.retention_days, "retention-days", 1)
    except ValueError as error:
        parser.error(str(error))
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    periodic_job_status.write_status(
        arguments.status_file,
        {
            "job": "backup",
            "enabled": True,
            "status": "WAITING",
            "lastStartedAt": None,
            "lastFinishedAt": None,
            "nextRunAt": periodic_job_status.future_timestamp(initial_delay_seconds),
            "lastBackup": None,
            "removedFiles": 0,
            "error": None,
        },
    )
    return run_scheduler(
        arguments.database,
        arguments.catalog,
        arguments.output_dir,
        arguments.lock_file,
        arguments.status_file,
        interval_seconds,
        initial_delay_seconds,
        retention_days,
        arguments.once,
    )


if __name__ == "__main__":
    raise SystemExit(main())
