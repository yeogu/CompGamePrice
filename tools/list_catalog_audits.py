#!/usr/bin/env python3
"""List recent catalog administrator changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


def audits(database_path: Path, limit: int) -> list[dict]:
    if not database_path.exists():
        return []
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'catalog_change_audit'
            """
        ).fetchone()
        if table is None:
            return []
        rows = connection.execute(
            """
            SELECT id, actor, action, store, external_product_id, game_id,
                   outcome, occurred_at, detail
            FROM catalog_change_audit
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "actor": row[1],
            "action": row[2],
            "store": row[3],
            "externalProductId": row[4],
            "gameId": row[5],
            "outcome": row[6],
            "occurredAt": row[7],
            "detail": row[8],
        }
        for row in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--limit", default=50, type=int)
    arguments = parser.parse_args()
    if arguments.limit < 1 or arguments.limit > 200:
        parser.error("limit must be between 1 and 200")
    print(json.dumps({"audits": audits(arguments.database, arguments.limit)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
