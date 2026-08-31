#!/usr/bin/env python3
"""Build one operational summary for the local administrator dashboard."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import audit_catalog_metadata
import catalog_storage
import dispatch_notification_outbox


STORE_NAMES = (
    "Steam",
    "GooglePlay",
    "AppleAppStore",
    "EpicGamesStore",
    "NintendoEShop",
)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def column_exists(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> bool:
    return column in {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def parsed_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def store_quality(document: dict, database: Path) -> list[dict]:
    stores = {
        product["store"]
        for game in document["games"]
        for product in game.get("products", [])
    }
    result = {
        store: {
            "store": store,
            "registeredProducts": 0,
            "pricedProducts": 0,
            "freshPrices": 0,
            "stalePrices": 0,
            "pendingReviews": 0,
            "lastSuccessfulCollectionAt": None,
        }
        for store in sorted(stores | set(STORE_NAMES))
    }
    for game in document["games"]:
        for product in game.get("products", []):
            result[product["store"]]["registeredProducts"] += 1
    if not database.exists():
        return list(result.values())
    freshness_limit = datetime.now(timezone.utc) - timedelta(hours=48)
    with sqlite3.connect(database) as connection:
        if table_exists(connection, "store_products"):
            rows = connection.execute(
                "SELECT store, last_successful_check_at FROM store_products"
            ).fetchall()
            for store, checked_at in rows:
                if store not in result:
                    continue
                result[store]["pricedProducts"] += 1
                observed = parsed_time(checked_at)
                if observed is not None and observed >= freshness_limit:
                    result[store]["freshPrices"] += 1
                else:
                    result[store]["stalePrices"] += 1
        if table_exists(connection, "catalog_sync_review"):
            rows = connection.execute(
                """
                SELECT provider, COUNT(*)
                FROM catalog_sync_review
                WHERE status = 'PENDING'
                GROUP BY provider
                """
            ).fetchall()
            for store, count in rows:
                if store in result:
                    result[store]["pendingReviews"] = count
        if table_exists(connection, "crawl_runs"):
            observed_column = (
                "COALESCE(finished_at, started_at)"
                if column_exists(connection, "crawl_runs", "finished_at")
                else "started_at"
            )
            rows = connection.execute(
                f"""
                SELECT store, MAX({observed_column})
                FROM crawl_runs
                WHERE status = 'SUCCEEDED'
                GROUP BY store
                """
            ).fetchall()
            for store, finished_at in rows:
                if store in result:
                    result[store]["lastSuccessfulCollectionAt"] = finished_at
    return list(result.values())


def collection_summary(database: Path) -> dict:
    if not database.exists():
        return {"recentFailures": 0, "lastFailure": None}
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'crawl_runs'
            """
        ).fetchone()
        if table is None:
            return {"recentFailures": 0, "lastFailure": None}
        failures = connection.execute(
            """
            SELECT store, error_message, started_at
            FROM crawl_runs
            WHERE status = 'FAILED'
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()
    return {
        "recentFailures": len(failures),
        "lastFailure": None if not failures else {
            "store": failures[0][0],
            "error": failures[0][1],
            "startedAt": failures[0][2],
        },
    }


def summary(catalog: Path, database: Path) -> dict:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(document)
    metadata = audit_catalog_metadata.audit(document)
    delivery = (
        dispatch_notification_outbox.delivery_status(database)
        if database.exists()
        else {"pending": 0, "retryable": 0, "exhausted": 0, "sent": 0}
    )
    return {
        "metadata": {
            "complete": metadata["completeCount"],
            "incomplete": metadata["incompleteCount"],
            "total": metadata["gameCount"],
        },
        "collection": collection_summary(database),
        "stores": store_quality(document, database),
        "notifications": delivery,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(summary(arguments.catalog, arguments.database), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
