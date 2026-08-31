#!/usr/bin/env python3
"""Run Steam snapshot collection and import it into the C++ application."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import os
from datetime import datetime, timezone

import collect_steam_snapshot as collector
import storage_retention
import database_backup


class PipelineAlreadyRunning(RuntimeError):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PipelineAlreadyRunning(
                f"Another Steam collection is already using {path}"
            ) from error
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os_getpid()}\nstartedAt={timestamp()}\n")
        lock_file.flush()
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def os_getpid() -> int:
    # Kept behind a function so lock metadata can be deterministic in tests.
    import os

    return os.getpid()


def run_pipeline(
    tracker: Path,
    catalog_path: Path,
    output_directory: Path,
    archive_directory: Path | None = None,
    country: str = "kr",
    language: str = "korean",
    timeout: float = 15.0,
    request_delay: float = 1.0,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    archive_retention_days: int = 90,
    log_paths: list[Path] | None = None,
    log_max_bytes: int = 1_048_576,
    log_keep_bytes: int = 524_288,
    database_path: Path | None = None,
    database_backup_directory: Path | None = None,
    database_backup_retention_days: int = 30,
    fetcher=None,
    command_runner=subprocess.run,
) -> int:
    started_at = timestamp()
    with exclusive_lock(output_directory / ".steam_pipeline.lock"):
        targets = collector.load_steam_targets(catalog_path)
        collection_arguments = {
            "targets": targets,
            "output_directory": output_directory,
            "country": country,
            "language": language,
            "timeout": timeout,
            "request_delay": request_delay,
            "max_attempts": max_attempts,
            "retry_delay": retry_delay,
            "archive_directory": archive_directory,
        }
        if fetcher is not None:
            collection_arguments["fetcher"] = fetcher
        success_count, failures = collector.collect_targets(**collection_arguments)

        import_exit_code = None
        if success_count > 0:
            completed = command_runner(
                [
                    str(tracker),
                    "collect-steam-all",
                    "--data-dir",
                    str(output_directory),
                ],
                check=False,
                env={
                    **os.environ,
                    "GAME_PRICE_CATALOG_PATH": str(catalog_path),
                },
            )
            import_exit_code = completed.returncode

        backup_path = None
        backup_files_removed = 0
        backup_error = ""
        if (
            import_exit_code == 0
            and database_path is not None
            and database_backup_directory is not None
        ):
            try:
                backup_path, backup_files_removed = database_backup.create_backup(
                    database_path,
                    database_backup_directory,
                    database_backup_retention_days,
                    catalog=catalog_path,
                )
            except Exception as error:
                backup_error = str(error)

        archive_files_removed = 0
        if archive_directory is not None:
            archive_files_removed = storage_retention.prune_archive(
                archive_directory, archive_retention_days
            )
        logs_trimmed = storage_retention.trim_logs(
            log_paths or [], log_max_bytes, log_keep_bytes
        )

        report = {
            "startedAt": started_at,
            "finishedAt": timestamp(),
            "targets": len(targets),
            "collected": success_count,
            "failures": [
                {"appId": app_id, "error": error} for app_id, error in failures
            ],
            "importExitCode": import_exit_code,
            "archiveFilesRemoved": archive_files_removed,
            "logsTrimmed": logs_trimmed,
            "databaseBackup": str(backup_path) if backup_path else None,
            "databaseBackupFilesRemoved": backup_files_removed,
            "databaseBackupError": backup_error or None,
        }
        collector.atomic_write(
            output_directory / "steam_pipeline_run.json",
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

        if failures or import_exit_code not in (None, 0) or backup_error:
            return 1
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", default="build/game_price_tracker", type=Path)
    parser.add_argument("--catalog", default="data/game_catalog.json", type=Path)
    parser.add_argument("--targets", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", default="snapshots/latest", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--country", default="kr")
    parser.add_argument("--language", default="korean")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--request-delay", default=1.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
    parser.add_argument("--archive-retention-days", default=90, type=int)
    parser.add_argument("--log-max-bytes", default=1_048_576, type=int)
    parser.add_argument("--log-keep-bytes", default=524_288, type=int)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--database-backup-dir", type=Path)
    parser.add_argument("--database-backup-retention-days", default=30, type=int)
    parser.add_argument(
        "--input",
        type=Path,
        help="Use one saved Steam response instead of the network (for tests).",
    )
    arguments = parser.parse_args()

    fetcher = None
    if arguments.input:
        raw = arguments.input.read_bytes()

        def fixture_fetch(app_id, _country, _language, _timeout):
            return raw, 200, f"fixture://steam/{app_id}"

        fetcher = fixture_fetch

    try:
        log_directory = arguments.output_dir.parent / "logs"
        database_path = arguments.database or Path(
            os.environ.get(
                "GAME_PRICE_DATABASE_PATH",
                str(arguments.tracker.parent / "game_prices.db"),
            )
        )
        catalog_path = arguments.catalog
        # Compatibility for an already-loaded legacy launchd definition.
        if arguments.targets is not None and catalog_path.name == "games.txt":
            catalog_path = catalog_path.with_name("game_catalog.json")
        return run_pipeline(
            arguments.tracker,
            catalog_path,
            arguments.output_dir,
            arguments.archive_dir or arguments.output_dir.parent / "archive",
            arguments.country,
            arguments.language,
            arguments.timeout,
            arguments.request_delay,
            arguments.max_attempts,
            arguments.retry_delay,
            arguments.archive_retention_days,
            [
                log_directory / "steam_pipeline.stdout.log",
                log_directory / "steam_pipeline.stderr.log",
            ],
            arguments.log_max_bytes,
            arguments.log_keep_bytes,
            database_path,
            arguments.database_backup_dir or arguments.output_dir.parent / "db-backups",
            arguments.database_backup_retention_days,
            fetcher,
        )
    except PipelineAlreadyRunning as error:
        print(error, file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as error:
        print(f"Steam pipeline configuration error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
