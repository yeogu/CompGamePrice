#!/usr/bin/env python3
"""Build one operational summary for the local administrator dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import audit_catalog_metadata
import catalog_storage
import dispatch_notification_outbox


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
