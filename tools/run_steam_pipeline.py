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
from datetime import datetime, timezone

import collect_steam_snapshot as collector


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
    targets_path: Path,
    output_directory: Path,
    catalog_path: Path | None = None,
    country: str = "kr",
    language: str = "korean",
    timeout: float = 15.0,
    request_delay: float = 1.0,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    fetcher=None,
    command_runner=subprocess.run,
) -> int:
    started_at = timestamp()
    with exclusive_lock(output_directory / ".steam_pipeline.lock"):
        targets = collector.load_targets(targets_path)
        if catalog_path is not None:
            collector.validate_targets_in_catalog(
                targets, collector.load_catalog_game_ids(catalog_path)
            )
        collection_arguments = {
            "targets": targets,
            "output_directory": output_directory,
            "country": country,
            "language": language,
            "timeout": timeout,
            "request_delay": request_delay,
            "max_attempts": max_attempts,
            "retry_delay": retry_delay,
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
            )
            import_exit_code = completed.returncode

        report = {
            "startedAt": started_at,
            "finishedAt": timestamp(),
            "targets": len(targets),
            "collected": success_count,
            "failures": [
                {"appId": app_id, "error": error} for app_id, error in failures
            ],
            "importExitCode": import_exit_code,
        }
        collector.atomic_write(
            output_directory / "steam_pipeline_run.json",
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

        if failures or import_exit_code not in (None, 0):
            return 1
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", default="build/game_price_tracker", type=Path)
    parser.add_argument(
        "--targets", default="data/steam_collection_targets.json", type=Path
    )
    parser.add_argument("--catalog", default="data/games.txt", type=Path)
    parser.add_argument("--output-dir", default="snapshots/latest", type=Path)
    parser.add_argument("--country", default="kr")
    parser.add_argument("--language", default="korean")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--request-delay", default=1.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
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
        return run_pipeline(
            arguments.tracker,
            arguments.targets,
            arguments.output_dir,
            arguments.catalog,
            arguments.country,
            arguments.language,
            arguments.timeout,
            arguments.request_delay,
            arguments.max_attempts,
            arguments.retry_delay,
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
