#!/usr/bin/env python3
"""Discover and approve canonical metadata proposed by verified Steam products."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import catalog_storage
import collect_steam_snapshot as steam
import update_catalog_game_metadata as metadata_update


def utc_now() -> str:
    return catalog_storage.utc_now()


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_metadata_review (
            game_id TEXT PRIMARY KEY,
            source_store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            proposed_json TEXT NOT NULL,
            diff_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )


def steam_product(game: dict) -> dict | None:
    return next(
        (
            product
            for product in game.get("products", [])
            if product.get("store") == "Steam"
        ),
        None,
    )


def proposed_metadata(raw: bytes, app_id: str) -> dict:
    document = json.loads(raw)
    entry = document.get(app_id)
    if not isinstance(entry, dict) or not entry.get("success"):
        raise ValueError(f"Steam product {app_id} was not found")
    data = entry.get("data")
    if not isinstance(data, dict) or data.get("type") != "game":
        raise ValueError(f"Steam product {app_id} is not a base game")
    return {
        "developers": [
            value.strip()
            for value in data.get("developers", [])
            if isinstance(value, str) and value.strip()
        ],
        "publishers": [
            value.strip()
            for value in data.get("publishers", [])
            if isinstance(value, str) and value.strip()
        ],
        "genres": [
            item["description"].strip()
            for item in data.get("genres", [])
            if isinstance(item, dict)
            and isinstance(item.get("description"), str)
            and item["description"].strip()
        ],
    }


def proposal_diff(game: dict, proposed: dict) -> dict:
    return {
        field: {
            "before": game.get(field, []),
            "after": values,
        }
        for field, values in proposed.items()
        if values and game.get(field, []) != values
    }


def missing_field_changes(game: dict, proposed: dict) -> dict:
    return {
        field: values
        for field, values in proposed.items()
        if values and not game.get(field)
    }


def identity_conflicts(game: dict, proposed: dict) -> dict:
    conflicts = {}
    for field in ("developers", "publishers"):
        current = game.get(field, [])
        candidate = proposed.get(field, [])
        if current and candidate and current != candidate:
            conflicts[field] = {
                "before": current,
                "after": candidate,
            }
    return conflicts


def fetch_steam_metadata(app_id: str) -> bytes:
    raw, _, _ = steam.fetch(app_id, "kr", "english", 15.0)
    return raw


def synchronize(
    catalog_path: Path,
    database_path: Path,
    limit: int = 20,
    fetcher=fetch_steam_metadata,
) -> dict:
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(document)
    discovered = 0
    auto_applied = 0
    failed = []
    with sqlite3.connect(database_path) as connection:
        initialize(connection)
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT game_id FROM catalog_metadata_review"
            )
        }
        candidates = [
            game
            for game in document["games"]
            if game["id"] not in existing
            and steam_product(game) is not None
            and (not game.get("developers") or not game.get("publishers"))
        ][:limit]
        for game in candidates:
            product = steam_product(game)
            app_id = str(product["productId"])
            try:
                proposed = proposed_metadata(fetcher(app_id), app_id)
                conflicts = identity_conflicts(game, proposed)
                changes = missing_field_changes(game, proposed)
                if conflicts:
                    connection.execute(
                        """
                        INSERT INTO catalog_metadata_review(
                            game_id, source_store, external_product_id,
                            proposed_json, diff_json, created_at
                        ) VALUES(?, 'Steam', ?, ?, ?, ?)
                        """,
                        (
                            game["id"],
                            app_id,
                            json.dumps(proposed, ensure_ascii=False),
                            json.dumps(conflicts, ensure_ascii=False),
                            utc_now(),
                        ),
                    )
                    discovered += 1
                    continue
                if changes:
                    metadata_update.update_metadata(
                        catalog_path,
                        game["id"],
                        changes,
                        True,
                        database_path,
                        "steam-metadata-sync",
                    )
                    auto_applied += 1
            except Exception as error:
                failed.append({"gameId": game["id"], "error": str(error)})
        connection.commit()
    return {
        "discovered": discovered,
        "autoApplied": auto_applied,
        "failed": failed,
        **status(database_path),
    }


def status(database_path: Path) -> dict:
    if not database_path.exists():
        return {"pendingReviews": [], "reviewHistory": []}
    with sqlite3.connect(database_path) as connection:
        initialize(connection)
        rows = connection.execute(
            """
            SELECT game_id, source_store, external_product_id,
                   proposed_json, diff_json, status, created_at, resolved_at
            FROM catalog_metadata_review
            ORDER BY created_at DESC
            """
        ).fetchall()
    reviews = [{
        "gameId": row[0],
        "sourceStore": row[1],
        "externalProductId": row[2],
        "proposed": json.loads(row[3]),
        "diff": json.loads(row[4]),
        "status": row[5],
        "createdAt": row[6],
        "resolvedAt": row[7],
    } for row in rows]
    return {
        "pendingReviews": [item for item in reviews if item["status"] == "PENDING"],
        "reviewHistory": [item for item in reviews if item["status"] != "PENDING"],
    }


def resolve(
    catalog_path: Path,
    database_path: Path,
    game_id: str,
    resolution: str,
) -> dict:
    if resolution not in {"APPROVED", "REJECTED"}:
        raise ValueError("resolution must be APPROVED or REJECTED")
    with sqlite3.connect(database_path) as connection:
        initialize(connection)
        row = connection.execute(
            """
            SELECT proposed_json, status
            FROM catalog_metadata_review
            WHERE game_id = ?
            """,
            (game_id,),
        ).fetchone()
        if row is None or row[1] != "PENDING":
            raise ValueError("pending metadata review does not exist")
        if resolution == "APPROVED":
            metadata_update.update_metadata(
                catalog_path,
                game_id,
                json.loads(row[0]),
                True,
                database_path,
            )
        connection.execute(
            """
            UPDATE catalog_metadata_review
            SET status = ?, resolved_at = ?
            WHERE game_id = ?
            """,
            (resolution, utc_now(), game_id),
        )
        connection.commit()
    return status(database_path)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--limit", default=20, type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--resolve-game-id")
    parser.add_argument("--resolution", choices=("APPROVED", "REJECTED"))
    arguments = parser.parse_args()
    if arguments.resolve_game_id:
        result = resolve(
            arguments.catalog,
            arguments.database,
            arguments.resolve_game_id,
            arguments.resolution or "",
        )
    elif arguments.status:
        result = status(arguments.database)
    else:
        result = synchronize(
            arguments.catalog,
            arguments.database,
            arguments.limit,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
