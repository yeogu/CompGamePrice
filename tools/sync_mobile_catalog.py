#!/usr/bin/env python3
"""Discover Google Play and Apple candidates for canonical catalog games."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time

import add_apple_catalog_game as apple_import
import add_google_play_catalog_game as google_import
import add_storefront_catalog_game as storefront_import
import search_apple_catalog as apple_search
import search_google_play_catalog as google_search
import sync_steam_catalog as catalog_sync
import catalog_matcher
import catalog_storage
import storefront_catalog


STORE_CONFIG = {
    "GooglePlay": {
        "catalogStore": "GooglePlay",
        "search": google_search.search,
        "fetch": lambda product_id, timeout: google_import.google_play.fetch(product_id, timeout),
        "metadata": google_import.verified_product,
        "update": google_import.updated_catalog,
    },
    "AppleAppStore": {
        "catalogStore": "AppleAppStore",
        "search": apple_search.search,
        "fetch": apple_import.fetch,
        "metadata": apple_import.apple_product,
        "update": apple_import.updated_catalog,
    },
    "NintendoEShop": {
        "catalogStore": "NintendoEShop",
        "search": lambda query, limit, timeout: storefront_catalog.search(
            "NintendoEShop",
            query,
            limit,
            timeout,
        ),
        "fetch": lambda product_id, timeout: storefront_catalog.fetch_product(
            "NintendoEShop",
            f"https://store.nintendo.co.kr/{product_id}",
            timeout,
        ),
        "metadata": lambda raw, product_id: storefront_catalog.verified_product(
            raw,
            "NintendoEShop",
            f"https://store.nintendo.co.kr/{product_id}",
        ),
        "update": lambda catalog, game_id, product_id, metadata: (
            storefront_import.updated_catalog(
                catalog,
                "NintendoEShop",
                f"https://store.nintendo.co.kr/{product_id}",
                game_id,
                metadata,
            )
        ),
    },
}
REJECTED_GAME_RECHECK_DAYS = 7


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def initialize_state(connection: sqlite3.Connection) -> None:
    catalog_sync.initialize_state(connection)
    ensure_column(connection, "catalog_sync_review", "game_id", "TEXT")
    ensure_column(connection, "catalog_sync_review", "decision", "TEXT")
    ensure_column(connection, "catalog_sync_runs", "retry_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "catalog_sync_runs", "summary_json", "TEXT")
    connection.commit()


def load_catalog(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 4 or not isinstance(document.get("games"), list):
        raise ValueError("Game catalog requires schemaVersion 4 and games")
    return document


def games_missing_store(catalog: dict, store: str) -> list[dict]:
    return [
        game
        for game in catalog["games"]
        if not any(product.get("store") == store for product in game.get("products", []))
    ]


def pending_games(
    connection: sqlite3.Connection,
    catalog: dict,
    provider: str,
    batch_size: int,
) -> list[dict]:
    processed = {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            """
            SELECT external_product_id, outcome, checked_at
            FROM catalog_sync_seen
            WHERE provider = ?
            """,
            (f"{provider}:game",),
        )
    }
    return [
        game
        for game in games_missing_store(catalog, STORE_CONFIG[provider]["catalogStore"])
        if should_process_game(processed.get(game.get("id")))
    ][:batch_size]


def should_process_game(previous: tuple[str, str] | None) -> bool:
    if previous is None:
        return True
    outcome, checked_at = previous
    if outcome not in {"NO_MATCH", "Rejected"}:
        return False
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return checked <= datetime.now(timezone.utc) - timedelta(
        days=REJECTED_GAME_RECHECK_DAYS
    )


def call_with_retry(operation, max_attempts: int, retry_counter: list[int]):
    last_error = None
    for attempt in range(max_attempts):
        try:
            return operation()
        except (OSError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < max_attempts:
                retry_counter[0] += 1
                time.sleep(2 ** attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("mobile catalog operation failed")


def candidate_metadata(
    provider: str,
    product_id: str,
    fetcher,
    metadata_parser,
    timeout: float,
    max_attempts: int,
    retry_counter: list[int],
) -> dict:
    raw = call_with_retry(
        lambda: fetcher(product_id, timeout),
        max_attempts,
        retry_counter,
    )
    return metadata_parser(raw, product_id)


def search_game_candidates(
    game: dict,
    searcher,
    timeout: float,
    max_attempts: int,
    retry_counter: list[int],
) -> list[dict]:
    candidates = []
    seen = set()
    for query in [game["title"], *game.get("aliases", [])]:
        results = call_with_retry(
            lambda query=query: searcher(query, 5, timeout),
            max_attempts,
            retry_counter,
        )
        for candidate in results:
            product_id = str(candidate.get("externalProductId", ""))
            if product_id and product_id not in seen:
                candidates.append(candidate)
                seen.add(product_id)
        if candidates:
            break
    return candidates


def best_candidate(
    game: dict,
    candidates: list[dict],
    provider: str,
    fetcher,
    metadata_parser,
    timeout: float,
    max_attempts: int,
    retry_counter: list[int],
) -> tuple[dict, dict, dict]:
    evaluated = []
    priority = {"ApprovedCandidate": 0, "NeedsReview": 1, "Rejected": 2}
    for candidate in candidates:
        product_id = str(candidate["externalProductId"])
        metadata = candidate_metadata(
            provider,
            product_id,
            fetcher,
            metadata_parser,
            timeout,
            max_attempts,
            retry_counter,
        )
        decision = catalog_matcher.evaluate(game, metadata)
        evaluated.append((candidate, metadata, decision))
        if decision["status"] == "ApprovedCandidate":
            break
    return min(evaluated, key=lambda item: priority[item[2]["status"]])


def record_game_processed(
    connection: sqlite3.Connection,
    provider: str,
    game_id: str,
    outcome: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_sync_seen(provider, external_product_id, outcome, checked_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(provider, external_product_id) DO UPDATE SET
            outcome = excluded.outcome,
            checked_at = excluded.checked_at
        """,
        (f"{provider}:game", game_id, outcome, utc_now()),
    )


def record_candidate(
    connection: sqlite3.Connection,
    provider: str,
    game: dict,
    candidate: dict,
    metadata: dict,
    decision: dict,
) -> None:
    product_id = candidate["externalProductId"]
    reason = "; ".join(decision.get("reasons", [])) or decision["status"]
    payload = {
        **candidate,
        **metadata,
        "gameId": game["id"],
        "matchDecision": decision,
    }
    status = "REJECTED" if decision["status"] == "Rejected" else "PENDING"
    connection.execute(
        """
        INSERT INTO catalog_sync_review(
            provider, external_product_id, title, reason, candidate_json,
            status, created_at, game_id, decision
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, external_product_id) DO UPDATE SET
            title = excluded.title,
            reason = excluded.reason,
            candidate_json = excluded.candidate_json,
            game_id = excluded.game_id,
            decision = excluded.decision
        """,
        (
            provider,
            product_id,
            metadata.get("title", candidate.get("title", "")),
            reason,
            json.dumps(payload, ensure_ascii=False),
            status,
            utc_now(),
            game["id"],
            decision["status"],
        ),
    )


def connect_approved_candidate(
    catalog_path: Path,
    database_path: Path,
    provider: str,
    game: dict,
    candidate: dict,
    metadata: dict,
    updater,
) -> None:
    product_id = str(candidate["externalProductId"])

    def update(current: dict) -> tuple[dict, dict]:
        updated, result = updater(
            current,
            game["id"],
            product_id,
            metadata,
        )
        if result["matchDecision"]["status"] != "ApprovedCandidate":
            raise ValueError("only approved mobile candidates can be auto-connected")
        return updated, result

    catalog_storage.update_catalog(
        catalog_path,
        update,
        store=STORE_CONFIG[provider]["catalogStore"],
        product_id=product_id,
        game_id=game["id"],
        database_path=database_path,
        actor="mobile-catalog-sync",
        action="AUTO_CONNECT_STORE_PRODUCT",
    )


def start_run(connection: sqlite3.Connection, provider: str, started_at: str) -> int:
    cursor = connection.execute(
        "INSERT INTO catalog_sync_runs(provider, status, started_at) VALUES(?, 'RUNNING', ?)",
        (provider, started_at),
    )
    connection.commit()
    return cursor.lastrowid


def increment_reason(report: dict, reason: str) -> None:
    reason_counts = report["reasonCounts"]
    reason_counts[reason] = reason_counts.get(reason, 0) + 1


def finish_run(
    connection: sqlite3.Connection,
    run_id: int,
    report: dict,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE catalog_sync_runs
        SET status = ?, finished_at = ?, processed_count = ?,
            accepted_count = ?, review_count = ?, skipped_count = ?,
            failed_count = ?, error_message = ?, retry_count = ?, summary_json = ?
        WHERE id = ?
        """,
        (
            report["status"],
            utc_now(),
            report["processed"],
            report["approvedCandidates"],
            report["needsReview"],
            report["rejected"],
            report["failed"],
            error,
            report["retries"],
            json.dumps(
                {
                    "reasonCounts": report["reasonCounts"],
                    "failures": report["errors"],
                    "exclusions": report["exclusions"],
                },
                ensure_ascii=False,
            ),
            run_id,
        ),
    )
    connection.commit()


def synchronize_provider(
    catalog_path: Path,
    database_path: Path,
    provider: str,
    batch_size: int,
    timeout: float = 15.0,
    max_attempts: int = 3,
    searcher=None,
    fetcher=None,
    metadata_parser=None,
) -> dict:
    if provider not in STORE_CONFIG:
        raise ValueError("unsupported catalog store")
    if not 1 <= batch_size <= 100:
        raise ValueError("batch size must be between 1 and 100")
    if not 1 <= max_attempts <= 5:
        raise ValueError("max attempts must be between 1 and 5")
    config = STORE_CONFIG[provider]
    searcher = searcher or config["search"]
    fetcher = fetcher or config["fetch"]
    metadata_parser = metadata_parser or config["metadata"]
    catalog = load_catalog(catalog_path)
    report = {
        "provider": provider,
        "status": "RUNNING",
        "processed": 0,
        "approvedCandidates": 0,
        "autoConnected": 0,
        "needsReview": 0,
        "rejected": 0,
        "failed": 0,
        "retries": 0,
        "errors": [],
        "exclusions": [],
        "reasonCounts": {},
    }
    started_at = utc_now()
    with sqlite3.connect(database_path) as connection:
        initialize_state(connection)
        run_id = start_run(connection, provider, started_at)
        games = pending_games(connection, catalog, provider, batch_size)
        for game in games:
            report["processed"] += 1
            retry_counter = [0]
            try:
                candidates = search_game_candidates(
                    game,
                    searcher,
                    timeout,
                    max_attempts,
                    retry_counter,
                )
                if not candidates:
                    record_game_processed(connection, provider, game["id"], "NO_MATCH")
                    increment_reason(report, "No Store search results")
                    report["exclusions"].append({
                        "gameId": game["id"],
                        "title": game.get("title", ""),
                        "reason": "No Store search results",
                    })
                    report["rejected"] += 1
                    continue
                candidate, metadata, decision = best_candidate(
                    game,
                    candidates,
                    provider,
                    fetcher,
                    metadata_parser,
                    timeout,
                    max_attempts,
                    retry_counter,
                )
                if decision["status"] == "ApprovedCandidate":
                    connect_approved_candidate(
                        catalog_path,
                        database_path,
                        provider,
                        game,
                        candidate,
                        metadata,
                        config["update"],
                    )
                else:
                    record_candidate(connection, provider, game, candidate, metadata, decision)
                for reason in decision.get("reasons", []):
                    increment_reason(report, reason)
                record_game_processed(connection, provider, game["id"], decision["status"])
                if decision["status"] == "ApprovedCandidate":
                    report["approvedCandidates"] += 1
                    report["autoConnected"] += 1
                elif decision["status"] == "NeedsReview":
                    report["needsReview"] += 1
                else:
                    report["rejected"] += 1
                    report["exclusions"].append({
                        "gameId": game["id"],
                        "title": metadata.get("title", game.get("title", "")),
                        "reason": "; ".join(decision.get("reasons", [])),
                        "externalProductId": candidate.get("externalProductId"),
                        "productUrl": candidate.get("productUrl"),
                    })
            except Exception as error:
                report["failed"] += 1
                report["errors"].append({
                    "gameId": game.get("id"),
                    "title": game.get("title", ""),
                    "reason": str(error),
                })
            finally:
                report["retries"] += retry_counter[0]
                connection.commit()
        report["status"] = "SUCCEEDED" if report["failed"] == 0 else "PARTIAL"
        error_message = (
            json.dumps(report["errors"], ensure_ascii=False)
            if report["errors"]
            else None
        )
        finish_run(connection, run_id, report, error_message)
    return report


def synchronization_status(database_path: Path, provider: str, limit: int = 20) -> dict:
    with sqlite3.connect(database_path) as connection:
        initialize_state(connection)
        reviews = connection.execute(
            """
            SELECT external_product_id, title, reason, status, created_at,
                   game_id, decision, candidate_json
            FROM catalog_sync_review
            WHERE provider = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (provider, limit),
        ).fetchall()
        runs = connection.execute(
            """
            SELECT id, status, started_at, finished_at, processed_count,
                   accepted_count, review_count, skipped_count, failed_count,
                   error_message, retry_count, summary_json
            FROM catalog_sync_runs
            WHERE provider = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (provider,),
        ).fetchall()
    return {
        "provider": provider,
        "pendingReviews": [review_document(row) for row in reviews if row[3] == "PENDING"],
        "reviewHistory": [review_document(row) for row in reviews if row[3] != "PENDING"],
        "recentRuns": [run_document(row) for row in runs],
    }


def review_document(row: tuple) -> dict:
    candidate = json.loads(row[7])
    return {
        "externalProductId": row[0],
        "title": row[1],
        "reason": row[2],
        "status": row[3],
        "createdAt": row[4],
        "gameId": row[5],
        "decision": row[6],
        "productUrl": candidate.get("productUrl"),
    }


def run_document(row: tuple) -> dict:
    summary = json.loads(row[11]) if row[11] else {}
    return {
        "id": row[0],
        "status": row[1],
        "startedAt": row[2],
        "finishedAt": row[3],
        "processed": row[4],
        "approvedCandidates": row[5],
        "needsReview": row[6],
        "rejected": row[7],
        "failed": row[8],
        "error": row[9],
        "retries": row[10],
        "reasonCounts": summary.get("reasonCounts", {}),
        "failures": summary.get("failures", []),
        "exclusions": summary.get("exclusions", []),
    }


def resolve_review(database_path: Path, provider: str, product_id: str, resolution: str) -> dict:
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
            (resolution, provider, product_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("pending catalog review was not found")
        connection.commit()
    return synchronization_status(database_path, provider)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=tuple(STORE_CONFIG), required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--batch-size", default=10, type=int)
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--resolve-product-id")
    parser.add_argument("--resolution", choices=("APPROVED", "REJECTED"))
    arguments = parser.parse_args()
    if arguments.resolve_product_id:
        if not arguments.resolution:
            parser.error("--resolution is required with --resolve-product-id")
        report = resolve_review(
            arguments.database,
            arguments.store,
            arguments.resolve_product_id,
            arguments.resolution,
        )
    elif arguments.status:
        report = synchronization_status(arguments.database, arguments.store)
    else:
        report = synchronize_provider(
            arguments.catalog,
            arguments.database,
            arguments.store,
            arguments.batch_size,
            arguments.timeout,
            arguments.max_attempts,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
