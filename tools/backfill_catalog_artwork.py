#!/usr/bin/env python3
"""Fill missing canonical artwork from already connected Store products."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import storefront_catalog
import sync_mobile_catalog
import sync_steam_metadata
import update_catalog_game_metadata as metadata_update
import image_quality


STORE_PRIORITY = (
    "Steam",
    "EpicGamesStore",
    "PlayStationStore",
    "MicrosoftStore",
    "NintendoEShop",
    "GooglePlay",
    "AppleAppStore",
)


def product_image(product: dict, timeout: float) -> str:
    store = product.get("store")
    product_id = str(product.get("productId", ""))
    product_url = str(product.get("productUrl", ""))
    if store == "Steam":
        raw = sync_steam_metadata.fetch_steam_metadata(product_id)
        metadata = sync_steam_metadata.proposed_metadata(raw, product_id)
    elif store == "EpicGamesStore":
        raw = storefront_catalog.fetch_product(store, product_url, timeout)
        metadata = storefront_catalog.verified_product(raw, store, product_url)
    else:
        config = sync_mobile_catalog.STORE_CONFIG.get(store)
        if config is None:
            return ""
        raw = config["fetch"](product_id, timeout)
        metadata = config["metadata"](raw, product_id)
    return metadata_update.normalized_image_url(metadata.get("imageUrl", ""))


def ordered_products(game: dict) -> list[dict]:
    priority = {store: index for index, store in enumerate(STORE_PRIORITY)}
    products = [
        product
        for product in game.get("products", [])
        if product.get("store") in priority
    ]
    return sorted(products, key=lambda product: priority[product["store"]])


def backfill(
    catalog_path: Path,
    database_path: Path,
    limit: int = 20,
    timeout: float = 15.0,
    image_fetcher=product_image,
    image_inspector=image_quality.inspect,
) -> dict:
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    candidates = []
    for game in document["games"]:
        current_url = str(game.get("imageUrl", ""))
        try:
            current_quality = image_inspector(current_url, timeout) if current_url else None
        except Exception:
            current_quality = None
        if current_quality is None or current_quality.score < 65:
            candidates.append((game, current_quality))
    attempted = 0
    updated = 0
    failures = []
    quality_rejected = 0
    for game, current_quality in candidates:
        if attempted >= limit:
            break
        products = ordered_products(game)
        if not products:
            continue
        attempted += 1
        errors = []
        best_url = ""
        best_quality = current_quality
        for product in products:
            try:
                image_url = image_fetcher(product, timeout)
                if not image_url:
                    continue
                candidate_quality = image_inspector(image_url, timeout)
                store_bonus = max(0, 6 - STORE_PRIORITY.index(product["store"]))
                candidate_score = candidate_quality.score + store_bonus
                best_score = best_quality.score if best_quality is not None else float("-inf")
                if candidate_score > best_score + 5:
                    best_url = image_url
                    best_quality = candidate_quality
                if candidate_score >= 90:
                    break
            except Exception as error:
                errors.append(f"{product['store']}: {error}")
        if best_url:
            metadata_update.update_metadata(
                catalog_path,
                game["id"],
                {"imageUrl": best_url},
                True,
                database_path,
                "artwork-quality-backfill",
            )
            updated += 1
        elif errors and current_quality is None:
            failures.append({"gameId": game["id"], "errors": errors})
        else:
            quality_rejected += 1
    return {
        "candidates": len(candidates),
        "attempted": attempted,
        "updated": updated,
        "qualityRejected": quality_rejected,
        "failed": failures,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default=root / "data" / "game_catalog.json",
        type=Path,
    )
    parser.add_argument(
        "--database",
        default=root / "build" / "game_prices.db",
        type=Path,
    )
    parser.add_argument("--limit", default=20, type=int)
    parser.add_argument("--timeout", default=15.0, type=float)
    arguments = parser.parse_args()
    if arguments.limit < 1:
        parser.error("--limit must be at least 1")
    result = backfill(
        arguments.catalog,
        arguments.database,
        arguments.limit,
        arguments.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
