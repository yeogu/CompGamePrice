#!/usr/bin/env python3
"""Discover Steam catalog games and collect prices for newly registered games."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import sync_steam_catalog as catalog_sync


def run_pipeline(
    project: Path,
    catalog: Path,
    database: Path,
    tracker: Path,
    output_directory: Path,
    batch_size: int,
    synchronizer=catalog_sync.synchronize,
    command_runner=subprocess.run,
) -> tuple[dict, int]:
    report = synchronizer(catalog, database, batch_size)
    previous_status = catalog_sync.synchronization_status(database)
    previous_collection = previous_status.get("priceCollection")
    retry_failed_collection = (
        previous_collection is not None
        and previous_collection.get("status") == "FAILED"
    )
    if report["accepted"] == 0 and not retry_failed_collection:
        catalog_sync.record_price_collection(
            database,
            "NOT_REQUIRED",
            None,
        )
        report["priceCollection"] = {"status": "NOT_REQUIRED", "exitCode": None}
        return report, 0
    catalog_sync.record_price_collection(database, "RUNNING", None)
    completed = command_runner(
        [
            sys.executable,
            str(project / "tools" / "run_steam_pipeline.py"),
            "--tracker",
            str(tracker),
            "--catalog",
            str(catalog),
            "--output-dir",
            str(output_directory),
            "--database",
            str(database),
        ],
        check=False,
        env={**os.environ, "GAME_PRICE_DATABASE_PATH": str(database)},
    )
    status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
    error = None if completed.returncode == 0 else "Steam price collection failed"
    catalog_sync.record_price_collection(
        database,
        status,
        completed.returncode,
        error,
    )
    report["priceCollection"] = {
        "status": status,
        "exitCode": completed.returncode,
        "error": error,
    }
    return report, completed.returncode


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=project / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=project / "build/game_prices.db", type=Path)
    parser.add_argument("--tracker", default=project / "build/game_price_tracker", type=Path)
    parser.add_argument("--output-dir", default=project / "snapshots/latest", type=Path)
    parser.add_argument("--batch-size", default=20, type=int)
    arguments = parser.parse_args()
    try:
        report, exit_code = run_pipeline(
            project,
            arguments.catalog,
            arguments.database,
            arguments.tracker,
            arguments.output_dir,
            arguments.batch_size,
        )
    except Exception as error:
        print(f"Catalog synchronization pipeline failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
