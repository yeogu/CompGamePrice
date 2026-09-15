#!/usr/bin/env python3
"""Collect one storefront snapshot and import it through the C++ domain path."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import collect_epic_snapshot
import collect_nintendo_snapshot
import collect_console_snapshot
import collect_ubisoft_snapshot
import collect_gog_snapshot
import collect_meta_quest_snapshot
import collect_ea_app_snapshot
import collect_battle_net_snapshot
import collect_itch_io_snapshot
import collect_humble_store_snapshot
import sync_steam_catalog as collection_status


def failure_category(error: str) -> str:
    return ("REGION_MISMATCH" if error.startswith("REGION_MISMATCH:")
            else "COLLECTION_FAILED")


def record_product_results(
    database: Path | None,
    store: str,
    product_ids: set[str],
    failures: list[tuple[str, str]],
) -> None:
    if database is None:
        return
    failed = dict(failures)
    with sqlite3.connect(database, timeout=30) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS catalog_product_collection_failures(
                provider TEXT NOT NULL,
                external_product_id TEXT NOT NULL,
                category TEXT NOT NULL,
                error_message TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                PRIMARY KEY(provider, external_product_id)
            )
        """)
        for product_id in product_ids - failed.keys():
            connection.execute("""
                DELETE FROM catalog_product_collection_failures
                WHERE provider = ? AND external_product_id = ?
            """, (store, product_id))
        for product_id, error in failures:
            connection.execute("""
                INSERT INTO catalog_product_collection_failures(
                    provider, external_product_id, category,
                    error_message, attempted_at
                ) VALUES(?, ?, ?, ?, datetime('now'))
                ON CONFLICT(provider, external_product_id) DO UPDATE SET
                    category = excluded.category,
                    error_message = excluded.error_message,
                    attempted_at = excluded.attempted_at
            """, (store, product_id, failure_category(error), error))
        connection.commit()


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
    "UbisoftStore": (
        collect_ubisoft_snapshot,
        "ubisoft_store_products.txt",
        "collect-ubisoft-all",
    ),
    "GOG": (
        collect_gog_snapshot,
        "gog_products.txt",
        "collect-gog-all",
    ),
    "MetaQuestStore": (
        collect_meta_quest_snapshot,
        "meta_quest_products.txt",
        "collect-meta-quest-all",
    ),
    "EAApp": (
        collect_ea_app_snapshot,
        "ea_app_products.txt",
        "collect-ea-app-all",
    ),
    "BattleNet": (
        collect_battle_net_snapshot,
        "battle_net_products.txt",
        "collect-battle-net-all",
    ),
    "ItchIo": (
        collect_itch_io_snapshot,
        "itch_io_products.txt",
        "collect-itch-io-all",
    ),
    "HumbleStore": (
        collect_humble_store_snapshot,
        "humble_store_products.txt",
        "collect-humble-store-all",
    ),
}

STORE_MAX_WORKERS = {
    "EpicGamesStore": 3,
    "NintendoEShop": 2,
    "PlayStationStore": 2,
    "MicrosoftStore": 2,
    "UbisoftStore": 3,
    "GOG": 4,
    "MetaQuestStore": 2,
    "EAApp": 3,
    "BattleNet": 3,
    "ItchIo": 4,
    "HumbleStore": 3,
}


def run_pipeline(
    store: str,
    tracker: Path,
    catalog: Path,
    output_directory: Path,
    database: Path | None = None,
    product_id: str | None = None,
) -> int:
    collector, filename, command = COLLECTORS[store]
    temporary_directory: Path | None = None
    selected_catalog = catalog
    output = output_directory / filename
    if product_id:
        output_directory.mkdir(parents=True, exist_ok=True)
        temporary_directory = Path(tempfile.mkdtemp(
            prefix="target-collection-",
            dir=output_directory,
        ))
        selected_catalog = temporary_directory / "catalog.json"
        output = temporary_directory / filename
        document = json.loads(catalog.read_text(encoding="utf-8"))
        games = []
        for game in document.get("games", []):
            products = [
                product for product in game.get("products", [])
                if product.get("store") == store
                and product.get("productId") == product_id
            ]
            if products:
                games.append({**game, "products": products})
        if not games:
            shutil.rmtree(temporary_directory)
            raise ValueError(f"unknown {store} product: {product_id}")
        document["games"] = games
        selected_catalog.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    selected_product_ids: set[str] = set()
    if selected_catalog.exists():
        selected_document = json.loads(selected_catalog.read_text(encoding="utf-8"))
        selected_product_ids = {
            product["productId"]
            for game in selected_document.get("games", [])
            for product in game.get("products", [])
            if product.get("store") == store and product.get("productId")
        }
    previous_workers = os.environ.get("STORE_COLLECTION_MAX_WORKERS")
    os.environ["STORE_COLLECTION_MAX_WORKERS"] = (
        previous_workers or str(STORE_MAX_WORKERS[store])
    )
    try:
        if collector is collect_console_snapshot:
            collected, failures = collector.collect(store, selected_catalog, output)
        else:
            collected, failures = collector.collect(selected_catalog, output)
    except Exception:
        if temporary_directory is not None:
            shutil.rmtree(temporary_directory)
        raise
    finally:
        if previous_workers is None:
            os.environ.pop("STORE_COLLECTION_MAX_WORKERS", None)
        else:
            os.environ["STORE_COLLECTION_MAX_WORKERS"] = previous_workers
    for product_id, error in failures:
        print(
            f"{store} partial collection failure: {product_id}: {error}",
            file=sys.stderr,
        )
    record_product_results(database, store, selected_product_ids, failures)
    if collected == 0 and not failures:
        if database is not None:
            collection_status.record_price_collection(
                database,
                "NOT_REQUIRED",
                0,
                None,
                store,
            )
        result = 0
        if temporary_directory is not None:
            shutil.rmtree(temporary_directory)
        return result
    if collected == 0:
        if database is not None:
            error = collection_error(failures, "No products were collected")
            collection_status.record_price_collection(
                database,
                "FAILED",
                1,
                error,
                store,
            )
        if temporary_directory is not None:
            shutil.rmtree(temporary_directory)
        return 1
    environment = dict(os.environ)
    environment["GAME_PRICE_CATALOG_PATH"] = str(catalog)
    if database is not None:
        environment["GAME_PRICE_DATABASE_PATH"] = str(database)
    completed = subprocess.run(
        [str(tracker), command, "--data-dir", str(output.parent)],
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        if database is not None:
            collection_status.record_price_collection(
                database,
                "FAILED",
                completed.returncode,
                "C++ snapshot import failed",
                store,
            )
        if temporary_directory is not None:
            shutil.rmtree(temporary_directory)
        return completed.returncode
    result = 2 if failures else 0
    if database is not None:
        status = "PARTIAL" if failures else "SUCCEEDED"
        error = collection_error(failures, "Partial product collection failure")
        collection_status.record_price_collection(
            database,
            status,
            result,
            error if failures else None,
            store,
        )
    if temporary_directory is not None:
        shutil.rmtree(temporary_directory)
    return result


def collection_error(
    failures: list[tuple[str, str]],
    fallback: str,
) -> str:
    if not failures:
        return fallback
    details = "; ".join(
        f"{product_id}: {error}"
        for product_id, error in failures[:5]
    )
    return f"{fallback}: {details}"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, choices=COLLECTORS)
    parser.add_argument("--tracker", default=root / "build/game_price_tracker", type=Path)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output-dir", default=root / "snapshots/latest", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--product-id")
    arguments = parser.parse_args()
    return run_pipeline(
        arguments.store,
        arguments.tracker,
        arguments.catalog,
        arguments.output_dir,
        arguments.database,
        arguments.product_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
