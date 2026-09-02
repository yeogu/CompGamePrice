#!/usr/bin/env python3
"""Run DealQuest collection operations periodically without overlapping runs."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time

import periodic_job_status
import run_daily_operations


MINIMUM_INTERVAL_SECONDS = 300
stop_requested = False


def request_stop(signum: int, frame: object) -> None:
    del signum
    del frame
    global stop_requested
    stop_requested = True


def run_once(
    project: Path,
    tracker: Path,
    database: Path,
    output_directory: Path,
    catalog_batch_size: int,
    status_path: Path | None = None,
) -> dict:
    started_at = time.time()
    started_at_text = periodic_job_status.timestamp()
    if status_path is not None:
        periodic_job_status.write_status(
            status_path,
            {
                "job": "collection",
                "enabled": True,
                "status": "RUNNING",
                "lastStartedAt": started_at_text,
                "lastFinishedAt": None,
                "nextRunAt": None,
                "failedSteps": [],
                "error": None,
            },
        )
    results = run_daily_operations.run_operations(
        project,
        tracker,
        database,
        output_directory,
        None,
        catalog_batch_size,
    )
    failed_steps = [result["name"] for result in results if result["exitCode"] != 0]
    summary = {
        "startedAtEpoch": started_at,
        "finishedAtEpoch": time.time(),
        "status": "SUCCEEDED" if not failed_steps else "PARTIAL_FAILURE",
        "failedSteps": failed_steps,
        "steps": results,
    }
    if status_path is not None:
        periodic_job_status.write_status(
            status_path,
            {
                "job": "collection",
                "enabled": True,
                "status": summary["status"],
                "lastStartedAt": started_at_text,
                "lastFinishedAt": periodic_job_status.timestamp(),
                "nextRunAt": None,
                "failedSteps": failed_steps,
                "error": None,
            },
        )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def run_scheduler(
    project: Path,
    tracker: Path,
    database: Path,
    output_directory: Path,
    lock_path: Path,
    interval_seconds: int,
    initial_delay_seconds: int,
    catalog_batch_size: int,
    single_run: bool = False,
    status_path: Path | None = None,
) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    output_directory.mkdir(parents=True, exist_ok=True)
    if status_path is None:
        status_path = Path("/tmp/dealquest-collection-status.json")
    periodic_job_status.wait_with_heartbeat(
        initial_delay_seconds,
        lambda: stop_requested,
        status_path,
        "collection",
    )
    while not stop_requested:
        lock_busy = False
        with lock_path.open("w", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock_busy = True
            if lock_busy:
                print(f"Collection cycle is already running: {lock_path}", file=sys.stderr)
            else:
                lock_file.write(str(os.getpid()))
                lock_file.flush()
                try:
                    run_once(
                        project,
                        tracker,
                        database,
                        output_directory,
                        catalog_batch_size,
                        status_path,
                    )
                except Exception as error:
                    print(
                        f"Collection cycle failed unexpectedly: {error}",
                        file=sys.stderr,
                        flush=True,
                    )
                    if status_path is not None:
                        periodic_job_status.write_status(
                            status_path,
                            {
                                "job": "collection",
                                "enabled": True,
                                "status": "FAILED",
                                "lastFinishedAt": periodic_job_status.timestamp(),
                                "nextRunAt": None,
                                "failedSteps": [],
                                "error": str(error),
                            },
                        )
        if single_run:
            return 2 if lock_busy else 0
        if status_path is not None:
            current = periodic_job_status.read_status(status_path, "collection")
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
            "collection",
        )
    return 0


def main() -> int:
    project = Path(os.environ.get("GAME_PRICE_PROJECT_PATH", Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracker",
        default=Path(os.environ.get("GAME_PRICE_TRACKER_PATH", project / "game_price_tracker")),
        type=Path,
    )
    parser.add_argument(
        "--database",
        default=Path(os.environ.get("GAME_PRICE_DATABASE_PATH", project / "build/game_prices.db")),
        type=Path,
    )
    parser.add_argument(
        "--output-dir",
        default=Path(os.environ.get("COLLECTION_OUTPUT_PATH", project / "snapshots/latest")),
        type=Path,
    )
    parser.add_argument(
        "--lock-file",
        default=Path(os.environ.get("COLLECTION_LOCK_PATH", "/tmp/dealquest-collection.lock")),
        type=Path,
    )
    parser.add_argument(
        "--interval-seconds",
        default=os.environ.get("COLLECTION_INTERVAL_SECONDS", "21600"),
    )
    parser.add_argument(
        "--initial-delay-seconds",
        default=os.environ.get("COLLECTION_INITIAL_DELAY_SECONDS", "120"),
    )
    parser.add_argument(
        "--catalog-batch-size",
        default=os.environ.get("COLLECTION_CATALOG_BATCH_SIZE", "20"),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one locked collection cycle and exit",
    )
    parser.add_argument(
        "--status-file",
        default=Path(
            os.environ.get(
                "COLLECTION_STATUS_PATH",
                "/tmp/dealquest-collection-status.json",
            )
        ),
        type=Path,
    )
    arguments = parser.parse_args()
    try:
        interval_seconds = periodic_job_status.parse_integer(
            arguments.interval_seconds,
            "interval-seconds",
            MINIMUM_INTERVAL_SECONDS,
        )
        initial_delay_seconds = periodic_job_status.parse_integer(
            arguments.initial_delay_seconds,
            "initial-delay-seconds",
        )
        catalog_batch_size = periodic_job_status.parse_integer(
            arguments.catalog_batch_size,
            "catalog-batch-size",
            1,
        )
        enabled = periodic_job_status.parse_boolean(
            os.environ.get("COLLECTION_ENABLED", "true"),
            "COLLECTION_ENABLED",
        )
    except ValueError as error:
        parser.error(str(error))
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if not enabled:
        periodic_job_status.write_status(
            arguments.status_file,
            {
                "job": "collection",
                "enabled": False,
                "status": "DISABLED",
                "lastStartedAt": None,
                "lastFinishedAt": None,
                "nextRunAt": None,
                "failedSteps": [],
                "error": None,
            },
        )
        print("Automatic collection is disabled by COLLECTION_ENABLED=false", flush=True)
        while not stop_requested:
            periodic_job_status.wait_with_heartbeat(
                60,
                lambda: stop_requested,
                arguments.status_file,
                "collection",
            )
        return 0
    periodic_job_status.write_status(
        arguments.status_file,
        {
            "job": "collection",
            "enabled": True,
            "status": "WAITING",
            "lastStartedAt": None,
            "lastFinishedAt": None,
            "nextRunAt": periodic_job_status.future_timestamp(initial_delay_seconds),
            "failedSteps": [],
            "error": None,
        },
    )
    return run_scheduler(
        project,
        arguments.tracker,
        arguments.database,
        arguments.output_dir,
        arguments.lock_file,
        interval_seconds,
        initial_delay_seconds,
        catalog_batch_size,
        arguments.once,
        arguments.status_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
