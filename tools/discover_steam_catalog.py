#!/usr/bin/env python3
"""Queue prioritized Steam catalog candidates from public Store lists."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import collect_steam_snapshot as steam
import search_steam_catalog as steam_search
import sync_steam_catalog as catalog_sync


SOURCES = (
    ("top-sellers", 300, {"filter": "topsellers"}),
    ("specials", 200, {"specials": "1"}),
    ("new-releases", 100, {"filter": "newreleases"}),
)


def fetch_source(parameters: dict[str, str], timeout: float = 15.0) -> bytes:
    query = urlencode({**parameters, "cc": "kr", "l": "koreana"})
    request = Request(
        f"https://store.steampowered.com/search/?{query}",
        headers={"User-Agent": steam.USER_AGENT},
    )
    with urlopen(request, timeout=timeout, context=steam.tls_context()) as response:
        return response.read()


def discover(fetcher=fetch_source, per_source_limit: int = 50) -> list[dict]:
    if not 1 <= per_source_limit <= 100:
        raise ValueError("per-source limit must be between 1 and 100")
    candidates = {}
    for source, priority, parameters in SOURCES:
        for candidate in steam_search.parse_results(
            fetcher(parameters),
            per_source_limit,
        ):
            app_id = candidate["externalProductId"]
            existing = candidates.get(app_id)
            if existing is None or priority > existing["priority"]:
                candidates[app_id] = {
                    "appId": app_id,
                    "title": candidate["title"],
                    "source": source,
                    "priority": priority,
                }
    return sorted(
        candidates.values(),
        key=lambda candidate: (-candidate["priority"], int(candidate["appId"])),
    )


def enqueue(database_path: Path, candidates: list[dict]) -> int:
    with sqlite3.connect(database_path) as connection:
        catalog_sync.initialize_state(connection)
        for candidate in candidates:
            connection.execute(
                """
                INSERT INTO catalog_discovery_candidates(
                    provider, external_product_id, title, source,
                    priority, status, discovered_at
                ) VALUES('Steam', ?, ?, ?, ?, 'PENDING', ?)
                ON CONFLICT(provider, external_product_id) DO UPDATE SET
                    title = excluded.title,
                    source = excluded.source,
                    priority = MAX(priority, excluded.priority),
                    discovered_at = excluded.discovered_at
                """,
                (
                    candidate["appId"],
                    candidate["title"],
                    candidate["source"],
                    candidate["priority"],
                    catalog_sync.utc_now(),
                ),
            )
        connection.commit()
    return len(candidates)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--per-source-limit", default=50, type=int)
    arguments = parser.parse_args()
    candidates = discover(per_source_limit=arguments.per_source_limit)
    queued = enqueue(arguments.database, candidates)
    print(json.dumps({"provider": "Steam", "queued": queued}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
