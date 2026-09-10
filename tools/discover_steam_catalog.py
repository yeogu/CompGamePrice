#!/usr/bin/env python3
"""Queue prioritized Steam catalog candidates from public Store lists."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import collect_steam_snapshot as steam
import search_steam_catalog as steam_search
import sync_steam_catalog as catalog_sync


SOURCES = (
    ("top-sellers", 300, {"filter": "topsellers"}),
    ("specials", 200, {"specials": "1"}),
    ("popular-new", 175, {"filter": "popularnew"}),
    ("new-releases", 100, {"filter": "newreleases"}),
    ("coming-soon", 50, {"filter": "comingsoon"}),
)


def retry_delay_seconds(error: HTTPError, fallback: float) -> float:
    retry_after = error.headers.get("Retry-After")
    try:
        return min(float(retry_after), 30.0) if retry_after else fallback
    except ValueError:
        return fallback


def fetch_source(
    parameters: dict[str, str],
    timeout: float = 15.0,
    max_attempts: int = 3,
    retry_delay: float = 2.0,
    sleeper=time.sleep,
) -> bytes:
    query = urlencode({**parameters, "cc": "kr", "l": "koreana"})
    request = Request(
        f"https://store.steampowered.com/search/?{query}",
        headers={"User-Agent": steam.USER_AGENT},
    )
    last_error = None
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=timeout, context=steam.tls_context()) as response:
                return response.read()
        except HTTPError as error:
            last_error = error
            transient = error.code in {408, 429} or 500 <= error.code < 600
            if not transient or attempt + 1 >= max_attempts:
                raise
            fallback = retry_delay * (2**attempt)
            sleeper(retry_delay_seconds(error, fallback))
        except (TimeoutError, URLError) as error:
            last_error = error
            if attempt + 1 >= max_attempts:
                raise
            sleeper(retry_delay * (2**attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Steam catalog source request failed")


def discover(
    fetcher=fetch_source,
    per_source_limit: int = 50,
    pages_per_source: int = 3,
    request_delay: float = 0.0,
    sleeper=time.sleep,
    failures: list[dict] | None = None,
) -> list[dict]:
    if not 1 <= per_source_limit <= 100:
        raise ValueError("per-source limit must be between 1 and 100")
    if not 1 <= pages_per_source <= 10:
        raise ValueError("pages-per-source must be between 1 and 10")
    candidates = {}
    request_count = 0
    for source, priority, parameters in SOURCES:
        for page in range(1, pages_per_source + 1):
            page_parameters = {**parameters, "page": str(page)}
            if request_count > 0 and request_delay > 0:
                sleeper(request_delay)
            request_count += 1
            try:
                raw = fetcher(page_parameters)
            except (HTTPError, TimeoutError, URLError) as error:
                if failures is not None:
                    failures.append(
                        {
                            "source": source,
                            "page": page,
                            "error": str(error),
                        }
                    )
                break
            for candidate in steam_search.parse_results(raw, per_source_limit):
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
    parser.add_argument("--pages-per-source", default=3, type=int)
    parser.add_argument("--request-delay", default=1.0, type=float)
    arguments = parser.parse_args()
    failures = []
    candidates = discover(
        per_source_limit=arguments.per_source_limit,
        pages_per_source=arguments.pages_per_source,
        request_delay=arguments.request_delay,
        failures=failures,
    )
    queued = enqueue(arguments.database, candidates)
    status = "PARTIAL" if failures else "SUCCEEDED"
    print(
        json.dumps(
            {
                "provider": "Steam",
                "status": status,
                "queued": queued,
                "failures": failures,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
