"""Retention helpers for generated Steam collection files."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


ARCHIVE_SUFFIXES = (".json.gz", ".metadata.json")


def prune_archive(
    archive_directory: Path,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        raise ValueError("Archive retention days must be at least 1")
    if not archive_directory.exists():
        return 0

    reference_time = now or datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(days=retention_days)
    removed = 0
    for path in archive_directory.glob("*/*"):
        if not path.is_file() or not path.name.endswith(ARCHIVE_SUFFIXES):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            path.unlink()
            removed += 1

    for directory in archive_directory.iterdir():
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return removed


def trim_log(path: Path, max_bytes: int, keep_bytes: int) -> bool:
    if max_bytes < 1 or keep_bytes < 1 or keep_bytes >= max_bytes:
        raise ValueError("Log limits require 0 < keep_bytes < max_bytes")
    if not path.is_file() or path.stat().st_size <= max_bytes:
        return False

    with path.open("rb") as source:
        source.seek(-keep_bytes, 2)
        tail = source.read()
    newline = tail.find(b"\n")
    if newline >= 0 and newline + 1 < len(tail):
        tail = tail[newline + 1:]

    temporary = path.with_name(f".{path.name}.retention.tmp")
    temporary.write_bytes(tail)
    temporary.replace(path)
    return True


def trim_logs(
    log_paths: list[Path],
    max_bytes: int,
    keep_bytes: int,
) -> int:
    return sum(trim_log(path, max_bytes, keep_bytes) for path in log_paths)
