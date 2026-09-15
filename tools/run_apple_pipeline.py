#!/usr/bin/env python3
"""Collect Apple App Store snapshots and import them into SQLite."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

import collect_apple_snapshot as collector
from run_storefront_price_pipeline import record_product_results


def run_pipeline(
    tracker: Path,
    catalog: Path,
    output_directory: Path,
    database: Path | None = None,
    product_id: str | None = None,
) -> int:
    output = output_directory / "apple_app_store_products.csv"
    collected, failures = (
        collector.collect(catalog, output)
        if product_id is None
        else collector.collect(catalog, output, product_id)
    )
    selected_product_ids = set()
    if catalog.exists():
        selected_product_ids = {
            track_id for track_id, _game_id in collector.apple_targets(catalog)
            if product_id is None or track_id == product_id
        }
    record_product_results(
        database, "AppleAppStore", selected_product_ids, failures
    )
    for track_id, error in failures:
        print(f"AppleAppStore partial collection failure: {track_id}: {error}")
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
    if completed.returncode != 0:
        return completed.returncode
    return 2 if failures else 0


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", default=root / "build/game_price_tracker", type=Path)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output-dir", default=root / "snapshots/latest", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--product-id")
    arguments = parser.parse_args()
    return run_pipeline(
        arguments.tracker,
        arguments.catalog,
        arguments.output_dir,
        arguments.database,
        arguments.product_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
