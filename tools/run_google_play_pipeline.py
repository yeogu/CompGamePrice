#!/usr/bin/env python3
"""Collect Google Play snapshots and import successful products into SQLite."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

import collect_google_play_snapshot as collector
from run_storefront_price_pipeline import record_product_results


def run_pipeline(
    tracker: Path,
    catalog: Path,
    output_directory: Path,
    database: Path | None = None,
    product_id: str | None = None,
) -> int:
    output = output_directory / "google_play_products.txt"
    if product_id is None:
        collected, failures = collector.collect(catalog, output)
    else:
        collected, failures = collector.collect(
            catalog,
            output,
            product_id=product_id,
        )
    for failed_product_id, error in failures:
        print(
            f"GooglePlay partial collection failure: {failed_product_id}: {error}",
            file=sys.stderr,
        )
    selected_product_ids = set()
    if catalog.exists():
        selected_product_ids = {
            package_name
            for package_name, _game_id in collector.google_play_targets(catalog)
            if product_id is None or package_name == product_id
        }
    record_product_results(
        database, "GooglePlay", selected_product_ids, failures
    )
    if collected == 0:
        return 1
    environment = dict(os.environ)
    environment["GAME_PRICE_CATALOG_PATH"] = str(catalog)
    if database is not None:
        environment["GAME_PRICE_DATABASE_PATH"] = str(database)
    completed = subprocess.run(
        [
            str(tracker),
            "collect-google-play-all",
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
