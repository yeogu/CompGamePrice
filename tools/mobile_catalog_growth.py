#!/usr/bin/env python3
"""Discover verified paid mobile games; free downloads may only link existing games."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import catalog_matcher
import catalog_storage
from sync_mobile_catalog import STORE_CONFIG
import collect_steam_snapshot as network_support
from audit_catalog_price_integrity import parsed_time

# Rotate bounded searches, rather than repeatedly registering the first results.
# Search results are only candidates: the product detail is authoritative.
QUERIES = ("유료 게임", "premium games", "puzzle", "role playing", "strategy",
           "adventure", "simulation", "레이싱", "보드 게임", "액션 게임")


def apple_paid_candidates():
    with urlopen("https://itunes.apple.com/kr/rss/toppaidapplications/limit=100/genre=6014/json",
                 timeout=15, context=network_support.tls_context()) as response:
        document = json.load(response)
    entries = document["feed"].get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    return [{"externalProductId": str(entry["id"]["attributes"]["im:id"])}
            for entry in entries]


def nintendo_switch2_candidates(timeout=15):
    """Discover purchasable full games from Nintendo Korea's official list."""
    page = 1
    total = None
    page_size = 24  # Nintendo's API currently caps this endpoint at 24.
    while total is None or (page - 1) * page_size < total:
        parameters = urlencode({"size": page_size, "spage": page, "sftab": "all"})
        request = Request(
            f"https://www.nintendo.com/kr/api/games/switch2?{parameters}",
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR"},
        )
        with urlopen(request, timeout=timeout,
                     context=network_support.tls_context()) as response:
            document = json.load(response)
        total = int(document.get("total", 0))
        items = document.get("items", [])
        if not items:
            break
        for item in items:
            product_id = str(item.get("nsuid", "")).strip()
            categories = set(item.get("category") or [])
            page_link = str(item.get("pageLink", ""))
            if (not product_id.isdigit() or product_id == "0000"
                    or "체험판" in categories
                    or not ("store.nintendo.co.kr" in page_link
                            or "{NSUID}" in page_link)):
                continue
            yield {
                "externalProductId": product_id,
                "title": str(item.get("title", "")).strip(),
                "platforms": ["NintendoSwitch2"],
                "releaseDate": str(item.get("releaseDate", "")),
            }
        page += 1


def price_confirmed(database, provider, product_id, started_at):
    store = {
        "AppleAppStore": "Apple App Store",
        "GooglePlay": "Google Play",
        "NintendoEShop": "Nintendo eShop",
    }[provider]
    with sqlite3.connect(database, timeout=30) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(store_products)")}
        if "last_successful_check_at" not in columns:
            return False
        row = db.execute("""SELECT last_successful_check_at FROM store_products
            WHERE store=? AND external_product_id=? AND currency='KRW' AND region='KR'
            AND purchasable=1""", (store, product_id)).fetchone()
    checked = parsed_time(row[0]) if row else None
    if checked and checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return bool(checked and checked.timestamp() >= int(started_at))


def apply_candidate(catalog: dict, provider: str, product_id: str, metadata: dict):
    if catalog_storage.find_product_game(catalog, provider, product_id):
        return catalog, {"outcome": "EXISTING"}
    if (not metadata.get("isGame") or not metadata.get("supportsTargetPlatform")
            or metadata.get("excludedWords")
            or catalog_matcher.price_status(metadata) not in {"PAID", "FREE"}):
        return catalog, {"outcome": "EXCLUDED"}
    if provider == "AppleAppStore" and not set(metadata.get("platforms", [])) & {"iOS", "iPadOS"}:
        return catalog, {"outcome": "EXCLUDED"}
    if provider == "NintendoEShop" and not set(metadata.get("platforms", [])) & {
            "NintendoSwitch", "NintendoSwitch2"}:
        return catalog, {"outcome": "EXCLUDED"}
    title = catalog_matcher.normalized_identity(metadata["title"])
    possible = [game for game in catalog["games"] if any(
        title == catalog_matcher.normalized_identity(value)
        or (catalog_matcher.normalized_identity(value) and
            (title in catalog_matcher.normalized_identity(value)
             or catalog_matcher.normalized_identity(value) in title))
        for value in [game["title"], *game.get("aliases", [])])]
    approved = [game for game in possible
                if any(title == catalog_matcher.normalized_identity(value)
                       for value in [game["title"], *game.get("aliases", [])])
                and catalog_matcher.evaluate(game, metadata)["status"] == "ApprovedCandidate"]
    if len(approved) == 1:
        updated, _ = STORE_CONFIG[provider]["update"](
            catalog, approved[0]["id"], product_id, metadata)
        return updated, {"outcome": "LINKED", "gameId": approved[0]["id"]}
    # Never turn an ambiguous cross-store match into a duplicate canonical game.
    if possible:
        return catalog, {"outcome": "NEEDS_REVIEW", "possibleGameIds": [game["id"] for game in possible]}
    if catalog_matcher.price_status(metadata) == "FREE" and provider != "NintendoEShop":
        return catalog, {"outcome": "FREE_ONLY_EXCLUDED"}
    if not metadata.get("developer", "").strip():
        return catalog, {"outcome": "NEEDS_REVIEW"}
    prefix = "nintendo-" if provider == "NintendoEShop" else "mobile-"
    game_id = prefix + hashlib.sha256(f"{provider}:{product_id}".encode()).hexdigest()[:20]
    platforms = (
        metadata.get("platforms", [])
        if provider in {"AppleAppStore", "NintendoEShop"}
        else ["Android"]
    )
    game = {"id": game_id, "title": metadata["title"], "aliases": [],
            "platforms": platforms,
            "developers": [metadata["developer"]], "publishers": [],
            "genres": [], "tags": [], "products": [],
            "imageUrl": metadata.get("imageUrl", "")}
    updated, _ = STORE_CONFIG[provider]["update"](
        {**catalog, "games": [*catalog["games"], game]}, game_id, product_id, metadata)
    return updated, {"outcome": "REGISTERED", "gameId": game_id}


def run(provider, catalog, database, tracker, output, batch_size=50):
    if not 1 <= batch_size <= 100:
        raise ValueError("mobile batch size must be 1..100")
    config = STORE_CONFIG[provider]
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = {"provider": provider, "registered": 0, "linked": 0, "failed": 0,
              "review": 0, "excluded": 0, "priceFailed": 0}
    with sqlite3.connect(database, timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS mobile_growth_cursor(provider TEXT PRIMARY KEY, cursor INTEGER NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS mobile_growth_candidates(
            provider TEXT, product_id TEXT, outcome TEXT NOT NULL DEFAULT 'PENDING',
            checked_at REAL NOT NULL DEFAULT 0, price_pending INTEGER NOT NULL DEFAULT 0,
            detail TEXT, PRIMARY KEY(provider, product_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS mobile_growth_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
            registered_count INTEGER NOT NULL DEFAULT 0,
            linked_count INTEGER NOT NULL DEFAULT 0,
            excluded_count INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            price_failed_count INTEGER NOT NULL DEFAULT 0)""")
        cursor = db.execute("SELECT cursor FROM mobile_growth_cursor WHERE provider=?", (provider,)).fetchone()
        cursor = cursor[0] if cursor else 0
        if provider == "AppleAppStore":
            try:
                for candidate in apple_paid_candidates():
                    db.execute("INSERT OR IGNORE INTO mobile_growth_candidates(provider,product_id) VALUES(?,?)",
                               (provider, candidate["externalProductId"]))
            except Exception as error:
                report["paidChartError"] = str(error)
                report["failed"] += 1
        elif provider == "NintendoEShop":
            try:
                candidates = list(nintendo_switch2_candidates())
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                # Process released titles first while preserving Nintendo's
                # newest-first order within that group. Preorders follow.
                candidates.sort(key=lambda item: item["releaseDate"] > now)
                for candidate in candidates:
                    db.execute(
                        "INSERT OR IGNORE INTO mobile_growth_candidates(provider,product_id) VALUES(?,?)",
                        (provider, candidate["externalProductId"]),
                    )
            except Exception as error:
                report["officialCatalogError"] = str(error)
                report["failed"] += 1
        # Discovery failure must not prevent retrying existing queued work.
        if provider != "NintendoEShop":
            try:
                for candidate in config["search"](QUERIES[cursor % len(QUERIES)], 20, 15):
                    db.execute("INSERT OR IGNORE INTO mobile_growth_candidates(provider,product_id) VALUES(?,?)",
                               (provider, str(candidate["externalProductId"])))
                db.execute("INSERT OR REPLACE INTO mobile_growth_cursor VALUES(?,?)", (provider, cursor + 1))
            except Exception as error:
                report["discoveryError"] = str(error)
                report["failed"] += 1
        db.commit()
        targets = db.execute("""SELECT product_id,price_pending FROM mobile_growth_candidates
            WHERE provider=? AND (outcome='PENDING' OR
                ((outcome='FAILED' OR price_pending=1) AND checked_at<?))
            ORDER BY price_pending DESC,checked_at,rowid LIMIT ?""",
            (provider, time.time() - 86400, batch_size)).fetchall()
        for product_id, price_pending in targets:
            time.sleep(1)
            try:
                if not price_pending:
                    metadata = config["metadata"](config["fetch"](product_id, 15), product_id)
                    result, _ = catalog_storage.update_catalog(
                        catalog, lambda current: apply_candidate(current, provider, product_id, metadata),
                        store=provider, product_id=product_id, game_id="",
                        database_path=database, actor="mobile-paid-discovery")
                    outcome = result["outcome"]
                    key = {"REGISTERED": "registered", "LINKED": "linked", "NEEDS_REVIEW": "review"}.get(outcome, "excluded")
                    report[key] += 1
                    # EXISTING also repairs interruption after catalog publication
                    # but before the durable first-price marker was committed.
                    price_pending = int(outcome in {"REGISTERED", "LINKED", "EXISTING"})
                    db.execute("UPDATE mobile_growth_candidates SET outcome=?,price_pending=?,checked_at=?,detail=? WHERE provider=? AND product_id=?",
                               (outcome, price_pending, time.time(), json.dumps({**result, "metadata": metadata}, ensure_ascii=False), provider, product_id))
                    db.commit()
                if price_pending:
                    started_at = time.time()
                    if provider == "AppleAppStore":
                        from run_apple_pipeline import run_pipeline
                        code = run_pipeline(tracker, catalog, output, database, product_id)
                    elif provider == "GooglePlay":
                        from run_google_play_pipeline import run_pipeline
                        code = run_pipeline(tracker, catalog, output, database, product_id)
                    else:
                        from run_storefront_price_pipeline import run_pipeline
                        code = run_pipeline(
                            "NintendoEShop", tracker, catalog, output,
                            database, product_id,
                        )
                    if code or not price_confirmed(database, provider, product_id, started_at):
                        report["priceFailed"] += 1
                    else:
                        db.execute("UPDATE mobile_growth_candidates SET price_pending=0 WHERE provider=? AND product_id=?", (provider, product_id))
                db.execute("UPDATE mobile_growth_candidates SET checked_at=? WHERE provider=? AND product_id=?", (time.time(), provider, product_id))
                db.commit()
            except Exception as error:
                report["failed"] += 1
                db.execute("UPDATE mobile_growth_candidates SET outcome='FAILED',checked_at=?,detail=? WHERE provider=? AND product_id=?",
                           (time.time(), str(error), provider, product_id))
                db.commit()
                if getattr(error, "code", None) in {401, 403, 429}:
                    break
        finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        status = "PARTIAL" if report["failed"] or report["priceFailed"] else "SUCCEEDED"
        db.execute("""INSERT INTO mobile_growth_runs(
            provider,status,started_at,finished_at,registered_count,linked_count,
            excluded_count,review_count,failed_count,price_failed_count)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                provider, status, started_at, finished_at, report["registered"],
                report["linked"], report["excluded"], report["review"],
                report["failed"], report["priceFailed"],
            ))
        db.commit()
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 2 if report["failed"] or report["priceFailed"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("AppleAppStore", "GooglePlay", "NintendoEShop"),
        required=True,
    )
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("MOBILE_CATALOG_BATCH_SIZE", "50")))
    for name in ("catalog", "database", "tracker", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.provider, args.catalog, args.database, args.tracker, args.output, args.batch_size))
