"""Shared status helpers for lightweight periodic container jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def future_timestamp(seconds: int, now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return timestamp(value + timedelta(seconds=seconds))


def parse_boolean(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def parse_integer(value: str, name: str, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


def write_status(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**document, "updatedAt": timestamp()}
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def read_status(path: Path, job: str) -> dict:
    fallback = {
        "job": job,
        "status": "NOT_STARTED",
        "enabled": None,
        "updatedAt": None,
    }
    if not path.is_file():
        return fallback
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            **fallback,
            "status": "UNKNOWN",
            "error": f"Cannot read job status: {error}",
        }
    if not isinstance(document, dict):
        return {**fallback, "status": "UNKNOWN", "error": "Invalid job status"}
    return {**fallback, **document}


def wait_with_heartbeat(
    seconds: int,
    should_stop: Callable[[], bool],
    status_path: Path,
    job: str,
) -> None:
    deadline = time.monotonic() + seconds
    next_heartbeat = time.monotonic() + 30
    while not should_stop():
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 0:
            return
        if now >= next_heartbeat:
            write_status(status_path, read_status(status_path, job))
            next_heartbeat = now + 30
        time.sleep(min(remaining, 1.0))
