#!/usr/bin/env python3
"""Check collection failures and stale product observations in SQLite."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collection_health(
    database: Path,
    stale_hours: int = 48,
    now: datetime | None = None,
) -> dict:
    if stale_hours < 1:
        raise ValueError("stale hours must be at least 1")
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=stale_hours)
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        latest_runs = connection.execute(
            """
            SELECT store, status, started_at, error_message
            FROM crawl_runs current
            WHERE id = (
                SELECT id FROM crawl_runs candidate
                WHERE candidate.store = current.store
                ORDER BY candidate.id DESC LIMIT 1
            )
            ORDER BY store
            """
        ).fetchall()
        stale_products = connection.execute(
            """
            SELECT store, external_product_id, last_successful_check_at
            FROM store_products
            WHERE last_successful_check_at IS NULL
               OR last_successful_check_at < ?
            ORDER BY store, external_product_id
            """,
            (cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z"),),
        ).fetchall()
    failed = [
        {"store": row[0], "status": row[1], "startedAt": row[2], "error": row[3]}
        for row in latest_runs
        if row[1] != "SUCCEEDED"
    ]
    stale = [
        {"store": row[0], "productId": row[1], "lastSuccessfulCheckAt": row[2]}
        for row in stale_products
    ]
    return {
        "healthy": not failed and not stale,
        "latestProviderRuns": len(latest_runs),
        "failedProviders": failed,
        "staleProducts": stale,
        "checkedAt": current.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="build/game_prices.db", type=Path)
    parser.add_argument("--stale-hours", default=48, type=int)
    arguments = parser.parse_args()
    try:
        result = collection_health(arguments.database, arguments.stale_hours)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
