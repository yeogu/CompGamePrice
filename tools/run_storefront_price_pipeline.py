#!/usr/bin/env python3
"""Collect one storefront snapshot and import it through the C++ domain path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

import collect_epic_snapshot
import collect_nintendo_snapshot
import collect_console_snapshot


COLLECTORS = {
    "EpicGamesStore": (
        collect_epic_snapshot,
        "epic_games_products.txt",
        "collect-epic-all",
    ),
    "NintendoEShop": (
        collect_nintendo_snapshot,
        "nintendo_eshop_products.csv",
        "collect-nintendo-all",
    ),
    "PlayStationStore": (
        collect_console_snapshot,
        "playstation_store_products.csv",
        "collect-playstation-all",
    ),
    "MicrosoftStore": (
        collect_console_snapshot,
        "microsoft_store_products.csv",
        "collect-microsoft-all",
    ),
}


def run_pipeline(
    store: str,
    tracker: Path,
    catalog: Path,
    output_directory: Path,
    database: Path | None = None,
) -> int:
    collector, filename, command = COLLECTORS[store]
    output = output_directory / filename
    if collector is collect_console_snapshot:
        collected, failures = collector.collect(store, catalog, output)
    else:
        collected, failures = collector.collect(catalog, output)
    if collected == 0:
        return 1
    environment = dict(os.environ)
    environment["GAME_PRICE_CATALOG_PATH"] = str(catalog)
    if database is not None:
        environment["GAME_PRICE_DATABASE_PATH"] = str(database)
    completed = subprocess.run(
        [str(tracker), command, "--data-dir", str(output_directory)],
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        return completed.returncode
    return 1 if failures else 0


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, choices=COLLECTORS)
    parser.add_argument("--tracker", default=root / "build/game_price_tracker", type=Path)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output-dir", default=root / "snapshots/latest", type=Path)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    return run_pipeline(
        arguments.store,
        arguments.tracker,
        arguments.catalog,
        arguments.output_dir,
        arguments.database,
    )


if __name__ == "__main__":
    raise SystemExit(main())
