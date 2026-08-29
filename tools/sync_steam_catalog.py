#!/usr/bin/env python3
"""Synchronize a bounded batch of Steam apps into the local game catalog."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from urllib.request import Request, urlopen

import add_steam_catalog_game as catalog_import
import collect_steam_snapshot as steam


APP_LIST_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
REVIEW_TITLE_PATTERN = re.compile(
    r"\b(dlc|demo|soundtrack|bundle|deluxe|ultimate|goty|season pass|upgrade)\b",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_app_list(timeout: float = 30.0) -> bytes:
    request = Request(APP_LIST_URL, headers={"User-Agent": steam.USER_AGENT})
    with urlopen(request, timeout=timeout, context=steam.tls_context()) as response:
        return response.read()


def parse_app_list(raw: bytes) -> list[dict]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Steam app list is malformed") from error
    apps = payload.get("applist", {}).get("apps")
    if not isinstance(apps, list):
        raise ValueError("Steam app list has no apps")
    results = []
    for app in apps:
        if not isinstance(app, dict):
            continue
        app_id = app.get("appid")
        name = app.get("name")
        if isinstance(app_id, int) and app_id > 0 and isinstance(name, str):
            results.append({"appId": str(app_id), "name": name.strip()})
    results.sort(key=lambda app: int(app["appId"]))
    return results


def initialize_state(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_sync_state (
            provider TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            last_app_id TEXT,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS catalog_sync_seen (
            provider TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            PRIMARY KEY(provider, external_product_id)
        );
        CREATE TABLE IF NOT EXISTS catalog_sync_review (
            provider TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            title TEXT NOT NULL,
            reason TEXT NOT NULL,
            candidate_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL,
            PRIMARY KEY(provider, external_product_id)
        );
        """
    )


def existing_steam_ids(catalog: dict) -> set[str]:
    return {
        str(product.get("productId"))
        for game in catalog.get("games", [])
        for product in game.get("products", [])
        if product.get("store") == "Steam"
    }


def pending_apps(
    connection: sqlite3.Connection,
    apps: list[dict],
    catalog: dict,
    batch_size: int,
) -> list[dict]:
    seen = {
        row[0]
        for row in connection.execute(
            "SELECT external_product_id FROM catalog_sync_seen WHERE provider = ?",
            ("Steam",),
        )
    }
    excluded = seen | existing_steam_ids(catalog)
    return [app for app in apps if app["appId"] not in excluded][:batch_size]


def review_reason(game: dict) -> str | None:
    if REVIEW_TITLE_PATTERN.search(game["title"]):
        return "title suggests a non-standard edition or related product"
    return None


def record_seen(
    connection: sqlite3.Connection,
    app_id: str,
    outcome: str,
    checked_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_sync_seen(provider, external_product_id, outcome, checked_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(provider, external_product_id) DO UPDATE SET
            outcome = excluded.outcome,
            checked_at = excluded.checked_at
        """,
        ("Steam", app_id, outcome, checked_at),
    )


def record_review(
    connection: sqlite3.Connection,
    app: dict,
    reason: str,
    candidate: dict | None,
    checked_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_sync_review(
            provider, external_product_id, title, reason,
            candidate_json, status, created_at
        ) VALUES(?, ?, ?, ?, ?, 'PENDING', ?)
        ON CONFLICT(provider, external_product_id) DO UPDATE SET
            title = excluded.title,
            reason = excluded.reason,
            candidate_json = excluded.candidate_json,
            status = 'PENDING'
        """,
        (
            "Steam",
            app["appId"],
            app["name"],
            reason,
            json.dumps(candidate or {}, ensure_ascii=False),
            checked_at,
        ),
    )


def update_state(
    connection: sqlite3.Connection,
    status: str,
    started_at: str,
    report: dict,
    error_message: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_sync_state(
            provider, status, started_at, finished_at, last_app_id,
            accepted_count, review_count, skipped_count, failed_count,
            error_message
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET
            status = excluded.status,
            started_at = excluded.started_at,
            finished_at = excluded.finished_at,
            last_app_id = excluded.last_app_id,
            accepted_count = excluded.accepted_count,
            review_count = excluded.review_count,
            skipped_count = excluded.skipped_count,
            failed_count = excluded.failed_count,
            error_message = excluded.error_message
        """,
        (
            "Steam",
            status,
            started_at,
            None if status == "RUNNING" else utc_now(),
            report.get("lastAppId"),
            report["accepted"],
            report["review"],
            report["skipped"],
            report["failed"],
            error_message,
        ),
    )
    connection.commit()


def synchronization_status(database_path: Path, review_limit: int = 20) -> dict:
    if not 1 <= review_limit <= 100:
        raise ValueError("review limit must be between 1 and 100")
    with sqlite3.connect(database_path) as connection:
        initialize_state(connection)
        row = connection.execute(
            """
            SELECT status, started_at, finished_at, last_app_id,
                   accepted_count, review_count, skipped_count, failed_count,
                   error_message
            FROM catalog_sync_state
            WHERE provider = ?
            """,
            ("Steam",),
        ).fetchone()
        reviews = connection.execute(
            """
            SELECT external_product_id, title, reason, status, created_at
            FROM catalog_sync_review
            WHERE provider = ? AND status = 'PENDING'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            ("Steam", review_limit),
        ).fetchall()
    result = {
        "provider": "Steam",
        "status": row[0] if row else "IDLE",
        "startedAt": row[1] if row else None,
        "finishedAt": row[2] if row else None,
        "lastAppId": row[3] if row else None,
        "accepted": row[4] if row else 0,
        "review": row[5] if row else 0,
        "skipped": row[6] if row else 0,
        "failed": row[7] if row else 0,
        "error": row[8] if row else None,
        "pendingReviews": [],
    }
    for review in reviews:
        result["pendingReviews"].append(
            {
                "externalProductId": review[0],
                "title": review[1],
                "reason": review[2],
                "status": review[3],
                "createdAt": review[4],
            }
        )
    return result


def resolve_review(
    database_path: Path,
    app_id: str,
    resolution: str,
) -> dict:
    if not app_id.isdigit():
        raise ValueError("Steam app id must be numeric")
    if resolution not in {"APPROVED", "REJECTED"}:
        raise ValueError("resolution must be APPROVED or REJECTED")
    with sqlite3.connect(database_path) as connection:
        initialize_state(connection)
        cursor = connection.execute(
            """
            UPDATE catalog_sync_review
            SET status = ?
            WHERE provider = ? AND external_product_id = ? AND status = 'PENDING'
            """,
            (resolution, "Steam", app_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("pending Steam catalog review was not found")
        record_seen(connection, app_id, resolution, utc_now())
        connection.commit()
    return {
        "provider": "Steam",
        "externalProductId": app_id,
        "status": resolution,
    }


def synchronize(
    catalog_path: Path,
    database_path: Path,
    batch_size: int,
    app_list_fetcher=fetch_app_list,
    detail_fetcher=None,
) -> dict:
    if not 1 <= batch_size <= 100:
        raise ValueError("batch size must be between 1 and 100")
    if detail_fetcher is None:
        detail_fetcher = lambda app_id: steam.fetch(
            app_id,
            "kr",
            "korean",
            15.0,
        )[0]
    started_at = utc_now()
    report = {
        "provider": "Steam",
        "status": "RUNNING",
        "accepted": 0,
        "review": 0,
        "skipped": 0,
        "failed": 0,
        "processed": 0,
        "lastAppId": None,
    }
    catalog = catalog_import.load_catalog(catalog_path)
    with sqlite3.connect(database_path) as connection:
        initialize_state(connection)
        update_state(connection, "RUNNING", started_at, report)
        try:
            apps = parse_app_list(app_list_fetcher())
            selected = pending_apps(connection, apps, catalog, batch_size)
            for app in selected:
                app_id = app["appId"]
                report["lastAppId"] = app_id
                report["processed"] += 1
                checked_at = utc_now()
                try:
                    game = catalog_import.catalog_game(detail_fetcher(app_id), app_id)
                    reason = review_reason(game)
                    if reason:
                        record_review(connection, app, reason, game, checked_at)
                        record_seen(connection, app_id, "REVIEW", checked_at)
                        report["review"] += 1
                        continue
                    catalog = catalog_import.updated_catalog(catalog, game)
                    record_seen(connection, app_id, "ACCEPTED", checked_at)
                    report["accepted"] += 1
                except catalog_import.CatalogImportError as error:
                    reason = str(error)
                    if "Only Steam base games" in reason:
                        record_seen(connection, app_id, "SKIPPED", checked_at)
                        report["skipped"] += 1
                    else:
                        record_review(connection, app, reason, None, checked_at)
                        record_seen(connection, app_id, "REVIEW", checked_at)
                        report["review"] += 1
                except Exception:
                    report["failed"] += 1
            if report["accepted"] > 0:
                catalog_import.write_catalog(catalog_path, catalog)
            report["status"] = "SUCCEEDED"
            update_state(connection, "SUCCEEDED", started_at, report)
            return report
        except Exception as error:
            connection.rollback()
            report["status"] = "FAILED"
            update_state(connection, "FAILED", started_at, report, str(error))
            raise


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--batch-size", default=20, type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--resolve-app-id")
    parser.add_argument("--resolution", choices=("APPROVED", "REJECTED"))
    arguments = parser.parse_args()
    try:
        if arguments.resolve_app_id:
            if not arguments.resolution:
                raise ValueError("--resolution is required with --resolve-app-id")
            report = resolve_review(
                arguments.database,
                arguments.resolve_app_id,
                arguments.resolution,
            )
        elif arguments.status:
            report = synchronization_status(arguments.database)
        else:
            report = synchronize(
                arguments.catalog,
                arguments.database,
                arguments.batch_size,
            )
    except (ValueError, OSError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
