#!/usr/bin/env python3
"""Create, verify, and safely restore SQLite backups."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def archive_name(now: datetime | None = None) -> str:
    return timestamp(now).replace("-", "").replace(":", "").replace(".", "")


def verify_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {path}")
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as error:
        raise RuntimeError(f"Cannot read SQLite database {path}: {error}") from error
    if result is None or result[0] != "ok":
        detail = result[0] if result else "no result"
        raise RuntimeError(f"SQLite integrity check failed for {path}: {detail}")


def verify_catalog(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Game catalog does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read Game Catalog {path}: {error}") from error
    if document.get("schemaVersion") != 4 or not isinstance(
        document.get("games"),
        list,
    ):
        raise RuntimeError(f"Invalid Game Catalog schema: {path}")
    return document


def copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(
            f"file:{source.resolve()}?mode=ro", uri=True
        ) as source_connection, sqlite3.connect(temporary) as destination_connection:
            source_connection.backup(destination_connection)
        verify_database(temporary)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def prune_backups(
    backup_directory: Path,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        raise ValueError("Database backup retention days must be at least 1")
    if not backup_directory.exists():
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    removed = 0
    for path in backup_directory.iterdir():
        if not path.is_file() or not (
            path.name.endswith(".db") or
            path.name.endswith(".metadata.json") or
            path.name.endswith(".catalog.json")
        ):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            path.unlink()
            removed += 1
    return removed


def create_backup(
    source: Path,
    backup_directory: Path,
    retention_days: int = 30,
    now: datetime | None = None,
    catalog: Path | None = None,
) -> tuple[Path, int]:
    verify_database(source)
    created_at = timestamp(now)
    name = f"game_prices_{archive_name(now)}"
    backup = backup_directory / f"{name}.db"
    metadata_path = backup_directory / f"{name}.metadata.json"
    copy_database(source, backup)
    catalog_backup = None
    if catalog is not None:
        verify_catalog(catalog)
        catalog_backup = backup_directory / f"{name}.catalog.json"
        catalog_backup.write_bytes(catalog.read_bytes())
    metadata = {
        "createdAt": created_at,
        "source": str(source.resolve()),
        "backup": str(backup.resolve()),
        "sizeBytes": backup.stat().st_size,
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "integrityCheck": "ok",
    }
    if catalog_backup is not None:
        metadata["catalogBackup"] = str(catalog_backup.resolve())
        metadata["catalogSha256"] = hashlib.sha256(
            catalog_backup.read_bytes()
        ).hexdigest()
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    removed = prune_backups(backup_directory, retention_days, now)
    return backup, removed


def restore_to_new_path(backup: Path, output: Path) -> None:
    verify_database(backup)
    if output.exists():
        raise FileExistsError(f"Restore output already exists: {output}")
    copy_database(backup, output)


def restore_catalog_to_new_path(backup: Path, output: Path) -> None:
    verify_catalog(backup)
    if output.exists():
        raise FileExistsError(f"Restore output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(backup.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", default="build/game_prices.db", type=Path)
    backup_parser.add_argument("--catalog", type=Path)
    backup_parser.add_argument(
        "--output-dir", default="snapshots/db-backups", type=Path
    )
    backup_parser.add_argument("--retention-days", default=30, type=int)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--backup", required=True, type=Path)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True, type=Path)
    restore_parser.add_argument("--output", required=True, type=Path)

    catalog_restore_parser = subparsers.add_parser("restore-catalog")
    catalog_restore_parser.add_argument("--backup", required=True, type=Path)
    catalog_restore_parser.add_argument("--output", required=True, type=Path)

    arguments = parser.parse_args()
    try:
        if arguments.command == "backup":
            path, removed = create_backup(
                arguments.database,
                arguments.output_dir,
                arguments.retention_days,
                catalog=arguments.catalog,
            )
            print(f"SQLite backup created: {path} ({removed} expired files removed)")
        elif arguments.command == "verify":
            verify_database(arguments.backup)
            print(f"SQLite backup integrity is ok: {arguments.backup}")
        elif arguments.command == "restore":
            restore_to_new_path(arguments.backup, arguments.output)
            print(f"SQLite backup restored to new path: {arguments.output}")
        else:
            restore_catalog_to_new_path(arguments.backup, arguments.output)
            print(f"Game Catalog backup restored to new path: {arguments.output}")
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
