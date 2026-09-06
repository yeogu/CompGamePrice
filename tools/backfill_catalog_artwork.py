#!/usr/bin/env python3
"""Fill missing canonical artwork from already connected Store products."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import storefront_catalog
import sync_mobile_catalog
import update_catalog_game_metadata as metadata_update


STORE_PRIORITY = (
    "PlayStationStore",
    "MicrosoftStore",
    "NintendoEShop",
    "EpicGamesStore",
    "GooglePlay",
    "AppleAppStore",
)


def product_image(product: dict, timeout: float) -> str:
    store = product.get("store")
    product_id = str(product.get("productId", ""))
    product_url = str(product.get("productUrl", ""))
    if store == "EpicGamesStore":
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
) -> dict:
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    missing = [game for game in document["games"] if not game.get("imageUrl")]
    attempted = 0
    updated = 0
    failures = []
    for game in missing:
        if attempted >= limit:
            break
        products = ordered_products(game)
        if not products:
            continue
        attempted += 1
        errors = []
        for product in products:
            try:
                image_url = image_fetcher(product, timeout)
                if not image_url:
                    continue
                metadata_update.update_metadata(
                    catalog_path,
                    game["id"],
                    {"imageUrl": image_url},
                    True,
                    database_path,
                    "artwork-backfill",
                )
                updated += 1
                break
            except Exception as error:
                errors.append(f"{product['store']}: {error}")
        else:
            failures.append({"gameId": game["id"], "errors": errors})
    return {
        "missing": len(missing),
        "attempted": attempted,
        "updated": updated,
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
