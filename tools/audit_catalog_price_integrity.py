#!/usr/bin/env python3
"""Find catalog products that cannot safely be exposed as current offers."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import catalog_storage


def parsed_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def catalog_products(document: dict) -> dict[tuple[str, str], dict]:
    products = {}
    for game in document["games"]:
        for product in game.get("products", []):
            products[(product["store"], product["productId"])] = {
                "gameId": game["id"],
                "gameTitle": game["title"],
                **product,
            }
    return products


def database_products(connection: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'store_products'"
    ).fetchone()
    if table is None:
        return {}
    rows = connection.execute(
        """
        SELECT store, external_product_id, game_id, purchasable,
               last_successful_check_at
        FROM store_products
        """
    ).fetchall()
    products = {}
    for store, product_id, game_id, purchasable, checked_at in rows:
        platforms = {
            row[0]
            for row in connection.execute(
                """
                SELECT platform FROM product_platforms
                WHERE store = ? AND external_product_id = ?
                """,
                (store, product_id),
            )
        }
        products[(store, product_id)] = {
            "gameId": game_id,
            "purchasable": bool(purchasable),
            "lastSuccessfulCheckAt": checked_at,
            "platforms": platforms,
        }
    return products


def issue(
    issue_type: str,
    severity: str,
    catalog_product: dict,
    reason: str,
) -> dict:
    return {
        "type": issue_type,
        "severity": severity,
        "store": catalog_product["store"],
        "productId": catalog_product["productId"],
        "gameId": catalog_product["gameId"],
        "gameTitle": catalog_product["gameTitle"],
        "reason": reason,
        "productUrl": catalog_product.get("productUrl", ""),
    }


def audit(catalog: Path, database: Path, stale_hours: int = 48) -> dict:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(document)
    registered = catalog_products(document)
    with sqlite3.connect(database) as connection:
        collected = database_products(connection)
    stale_limit = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    issues = []
    for key, product in registered.items():
        observed = collected.get(key)
        if observed is None:
            issues.append(issue(
                "MISSING_PRICE",
                "ERROR",
                product,
                "Store 연결은 있지만 수집된 가격이 없습니다.",
            ))
            continue
        if observed["gameId"] != product["gameId"]:
            issues.append(issue(
                "GAME_MISMATCH",
                "ERROR",
                product,
                f"가격 데이터가 다른 게임({observed['gameId']})에 연결되어 있습니다.",
            ))
        if not observed["purchasable"]:
            issues.append(issue(
                "NOT_PURCHASABLE",
                "WARNING",
                product,
                "현재 구매 불가 상태입니다.",
            ))
        checked_at = parsed_time(observed["lastSuccessfulCheckAt"])
        if checked_at is None or checked_at < stale_limit:
            issues.append(issue(
                "STALE_PRICE",
                "WARNING",
                product,
                "가격이 48시간 이상 성공적으로 확인되지 않았습니다.",
            ))
        catalog_platforms = set(product.get("platforms", []))
        if catalog_platforms and observed["platforms"] and not (
            catalog_platforms & observed["platforms"]
        ):
            issues.append(issue(
                "PLATFORM_MISMATCH",
                "ERROR",
                product,
                "카탈로그와 가격 데이터의 지원 플랫폼이 일치하지 않습니다.",
            ))
    for key, observed in collected.items():
        if key in registered:
            continue
        store, product_id = key
        issues.append({
            "type": "ORPHAN_PRICE",
            "severity": "WARNING",
            "store": store,
            "productId": product_id,
            "gameId": observed["gameId"],
            "gameTitle": observed["gameId"],
            "reason": "가격 데이터에만 존재하고 카탈로그 연결이 없습니다.",
            "productUrl": "",
        })
    counts = {}
    for entry in issues:
        counts[entry["type"]] = counts.get(entry["type"], 0) + 1
    return {
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "catalogProductCount": len(registered),
        "issueCount": len(issues),
        "counts": counts,
        "issues": issues,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--stale-hours", default=48, type=int)
    arguments = parser.parse_args()
    print(json.dumps(
        audit(arguments.catalog, arguments.database, arguments.stale_hours),
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
