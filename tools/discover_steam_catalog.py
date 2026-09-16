#!/usr/bin/env python3
"""Queue prioritized Steam catalog candidates from public Store lists."""

from __future__ import annotations

import argparse
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
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
    ("all-games", 150, {"sort_by": "Name_ASC"}),
    ("new-releases", 100, {"filter": "newreleases"}),
    ("coming-soon", 50, {"filter": "comingsoon"}),
)


def retry_delay_seconds(error: HTTPError, fallback: float) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    try:
        seconds = float(retry_after) if retry_after else fallback
        return max(0.0, seconds) if math.isfinite(seconds) else fallback
    except (ValueError, TypeError):
        try:
            return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return fallback


def initialize_discovery_state(connection: sqlite3.Connection) -> None:
    catalog_sync.initialize_state(connection)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_discovery_cursors (
            provider TEXT NOT NULL,
            source TEXT NOT NULL,
            next_page INTEGER NOT NULL DEFAULT 1,
            last_fingerprint TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, source)
        );
        CREATE TABLE IF NOT EXISTS catalog_discovery_cooldowns (
            provider TEXT PRIMARY KEY,
            resume_after REAL NOT NULL
        );
        """
    )


def page_fingerprint(results: list[dict]) -> str:
    return hashlib.sha256(
        ",".join(candidate["externalProductId"] for candidate in results).encode()
    ).hexdigest()


def source_error(error: Exception, source: str, page: int) -> dict:
    result = {"source": source, "page": page, "error": str(error)}
    if isinstance(error, HTTPError):
        result["httpStatus"] = error.code
        if error.code == 429:
            result["retryAfterSeconds"] = retry_delay_seconds(error, 300.0)
    return result


def fetch_source(
    parameters: dict[str, str],
    timeout: float = 15.0,
    max_attempts: int = 3,
    retry_delay: float = 2.0,
    sleeper=time.sleep,
) -> bytes:
    query = urlencode({**parameters, "category1": "998", "cc": "kr", "l": "koreana"})
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
            # A 429 applies to this provider, not just one search list. Let the
            # persistent discovery job defer every source instead of retrying it.
            if error.code == 429 or not transient or attempt + 1 >= max_attempts:
                raise
            fallback = retry_delay * (2**attempt)
            delay = retry_delay_seconds(error, fallback)
            if delay > 30:
                raise
            sleeper(delay)
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
    cursors: dict[str, int] | None = None,
    fingerprints: dict[str, str] | None = None,
    on_page=None,
) -> list[dict]:
    if not 1 <= per_source_limit <= 100:
        raise ValueError("per-source limit must be between 1 and 100")
    if not 1 <= pages_per_source <= 10:
        raise ValueError("pages-per-source must be between 1 and 10")
    candidates = {}
    request_count = 0
    for source, priority, parameters in SOURCES:
        first_page = max(1, (cursors or {}).get(source, 1))
        previous_fingerprint = (fingerprints or {}).get(source)
        for page in range(first_page, first_page + pages_per_source):
            page_parameters = {**parameters, "page": str(page)}
            if request_count > 0 and request_delay > 0:
                sleeper(request_delay)
            request_count += 1
            try:
                raw = fetcher(page_parameters)
                results = steam_search.parse_results(raw, per_source_limit)
                if not results and b"search_result" not in raw:
                    raise ValueError("Steam search response did not contain a results container")
            except (HTTPError, TimeoutError, URLError) as error:
                if failures is not None:
                    failures.append(source_error(error, source, page))
                if isinstance(error, HTTPError) and error.code in {403, 429}:
                    return sorted(candidates.values(), key=lambda item: (-item["priority"], int(item["appId"])))
                break
            except (ValueError, UnicodeError) as error:
                if failures is not None:
                    failures.append(source_error(error, source, page))
                break
            fingerprint = page_fingerprint(results)
            # Empty pages, or a server repeating its final page, end a traversal.
            exhausted = not results or fingerprint == previous_fingerprint
            page_candidates = []
            for candidate in results:
                app_id = candidate["externalProductId"]
                item = {
                    "appId": app_id,
                    "title": candidate["title"],
                    "source": source,
                    "priority": priority,
                }
                page_candidates.append(item)
                existing = candidates.get(app_id)
                if existing is None or priority > existing["priority"]:
                    candidates[app_id] = item
            next_page = 1 if exhausted else page + 1
            next_fingerprint = None if exhausted else fingerprint
            if on_page is not None:
                on_page(source, next_page, next_fingerprint, page_candidates)
            if cursors is not None:
                cursors[source] = next_page
            previous_fingerprint = next_fingerprint
            if exhausted:
                break
    return sorted(
        candidates.values(),
        key=lambda candidate: (-candidate["priority"], int(candidate["appId"])),
    )


def enqueue_candidates(connection: sqlite3.Connection, candidates: list[dict]) -> int:
    queued = 0
    for candidate in candidates:
        seen = connection.execute(
            "SELECT 1 FROM catalog_sync_seen WHERE provider = 'Steam' AND external_product_id = ?",
            (candidate["appId"],),
        ).fetchone() is not None
        inserted = connection.execute(
            """
            INSERT OR IGNORE INTO catalog_discovery_candidates(
                provider, external_product_id, title, source,
                priority, status, discovered_at
            ) VALUES('Steam', ?, ?, ?, ?, ?, ?)
            """,
            (candidate["appId"], candidate["title"], candidate["source"],
             candidate["priority"], "PROCESSED" if seen else "PENDING", catalog_sync.utc_now()),
        ).rowcount
        queued += inserted if not seen else 0
        if not inserted:
            connection.execute(
                """
                UPDATE catalog_discovery_candidates SET
                    title = ?,
                    source = CASE WHEN priority < ? THEN ? ELSE source END,
                    priority = MAX(priority, ?),
                    status = CASE WHEN ? THEN 'PROCESSED' ELSE status END
                WHERE provider = 'Steam' AND external_product_id = ?
                """,
                (candidate["title"], candidate["priority"], candidate["source"],
                 candidate["priority"], seen, candidate["appId"]),
            )
    return queued


def enqueue(database_path: Path, candidates: list[dict]) -> int:
    with sqlite3.connect(database_path, timeout=30) as connection:
        catalog_sync.initialize_state(connection)
        return enqueue_candidates(connection, candidates)


def run_discovery(database_path: Path, *, fetcher=fetch_source, per_source_limit=50,
                  pages_per_source=2, request_delay=1.0, sleeper=time.sleep, clock=time.time) -> dict:
    with sqlite3.connect(database_path, timeout=30) as connection:
        initialize_discovery_state(connection)
        state = connection.execute(
            "SELECT source, next_page, last_fingerprint FROM catalog_discovery_cursors WHERE provider = 'Steam'"
        ).fetchall()
        cooldown = connection.execute(
            "SELECT resume_after FROM catalog_discovery_cooldowns WHERE provider = 'Steam'"
        ).fetchone()
        cursors = {row[0]: row[1] for row in state}
        fingerprints = {row[0]: row[2] for row in state}
        result = {"provider": "Steam", "queued": 0, "discovered": 0, "existing": 0,
                  "failures": [], "pagesFetched": 0}
        if cooldown and cooldown[0] > clock():
            result.update(status="DEFERRED", retryAfterSeconds=math.ceil(cooldown[0] - clock()))
        else:
            def persist_page(source, next_page, fingerprint, candidates):
                with connection:
                    result["queued"] += enqueue_candidates(connection, candidates)
                    connection.execute(
                        """INSERT INTO catalog_discovery_cursors(provider, source, next_page, last_fingerprint, updated_at)
                        VALUES('Steam', ?, ?, ?, ?)
                        ON CONFLICT(provider, source) DO UPDATE SET next_page = excluded.next_page,
                            last_fingerprint = excluded.last_fingerprint, updated_at = excluded.updated_at""",
                        (source, next_page, fingerprint, catalog_sync.utc_now()),
                    )
                result["pagesFetched"] += 1

            candidates = discover(fetcher, per_source_limit, pages_per_source, request_delay,
                                  sleeper, result["failures"], cursors, fingerprints, persist_page)
            result["discovered"] = len(candidates)
            result["existing"] = len(candidates) - result["queued"]
            result["status"] = ("PARTIAL" if candidates else "FAILED") if result["failures"] else "SUCCEEDED"
            limited = next((error for error in result["failures"] if error.get("httpStatus") == 429), None)
            if limited:
                delay = max(60.0, limited["retryAfterSeconds"])
                with connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO catalog_discovery_cooldowns(provider, resume_after) VALUES('Steam', ?)",
                        (clock() + delay,),
                    )
                result["retryAfterSeconds"] = math.ceil(delay)
        result["pending"] = connection.execute(
            "SELECT COUNT(*) FROM catalog_discovery_candidates WHERE provider = 'Steam' AND status = 'PENDING'"
        ).fetchone()[0]
        result["nextPages"] = cursors
        return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--per-source-limit", default=50, type=int)
    parser.add_argument("--pages-per-source", default=2, type=int)
    parser.add_argument("--request-delay", default=1.0, type=float)
    arguments = parser.parse_args()
    result = run_discovery(
        arguments.database,
        per_source_limit=arguments.per_source_limit,
        pages_per_source=arguments.pages_per_source,
        request_delay=arguments.request_delay,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
