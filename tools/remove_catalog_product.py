#!/usr/bin/env python3
"""Safely disconnect one Store product from the canonical game catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import catalog_storage


def removed_catalog(
    document: dict,
    store: str,
    product_id: str,
) -> tuple[dict, dict]:
    game = catalog_storage.find_product_game(document, store, product_id)
    if game is None:
        raise ValueError("Store product is not connected to the catalog")
    remaining_products = [
        product
        for product in game.get("products", [])
        if not (
            product.get("store") == store and
            product.get("productId") == product_id
        )
    ]
    removed_game = not remaining_products
    if removed_game:
        games = [item for item in document["games"] if item is not game]
    else:
        updated_game = {**game, "products": remaining_products}
        games = [updated_game if item is game else item for item in document["games"]]
    return {
        **document,
        "games": games,
    }, {
        "store": store,
        "externalProductId": product_id,
        "gameId": game["id"],
        "title": game["title"],
        "removedGame": removed_game,
    }


def remove_product(
    catalog_path: Path,
    database_path: Path,
    store: str,
    product_id: str,
    apply: bool,
) -> dict:
    def update(current: dict) -> tuple[dict, dict]:
        return removed_catalog(current, store, product_id)

    if apply:
        current = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog_storage.validate_catalog(current)
        game = catalog_storage.find_product_game(current, store, product_id)
        if game is None:
            raise ValueError("Store product is not connected to the catalog")
        result, changed = catalog_storage.update_catalog(
            catalog_path,
            update,
            store=store,
            product_id=product_id,
            game_id=game["id"],
            database_path=database_path,
            actor="catalog-admin",
            action="DISCONNECT_STORE_PRODUCT",
        )
        return {**result, "applied": changed}
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(document)
    _, result = removed_catalog(document, store, product_id)
    return {**result, "applied": False}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        result = remove_product(
            arguments.catalog,
            arguments.database,
            arguments.store,
            arguments.product_id,
            arguments.apply,
        )
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
