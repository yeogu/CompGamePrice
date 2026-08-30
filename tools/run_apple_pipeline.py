#!/usr/bin/env python3
"""Collect Apple App Store snapshots and import them into SQLite."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

import collect_apple_snapshot as collector


def run_pipeline(
    tracker: Path,
    catalog: Path,
    output_directory: Path,
    database: Path | None = None,
) -> int:
    output = output_directory / "apple_app_store_products.csv"
    collected = collector.collect(catalog, output)
    if collected == 0:
        return 1
    environment = dict(os.environ)
    environment["GAME_PRICE_CATALOG_PATH"] = str(catalog)
    if database is not None:
        environment["GAME_PRICE_DATABASE_PATH"] = str(database)
    completed = subprocess.run(
        [
            str(tracker),
            "collect-apple-all",
            "--data-dir",
            str(output_directory),
        ],
        check=False,
        env=environment,
    )
    return completed.returncode


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", default=root / "build/game_price_tracker", type=Path)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output-dir", default=root / "snapshots/latest", type=Path)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    return run_pipeline(
        arguments.tracker,
        arguments.catalog,
        arguments.output_dir,
        arguments.database,
    )


if __name__ == "__main__":
    raise SystemExit(main())
