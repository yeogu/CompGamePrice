#!/usr/bin/env python3
"""Preview or attach an Epic/Nintendo product to a canonical game."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import catalog_matcher
import catalog_storage
import storefront_catalog


def updated_catalog(
    catalog: dict,
    store: str,
    product_url: str,
    game_id: str,
    metadata: dict,
    acknowledge_review: bool = False,
) -> tuple[dict, dict]:
    if (
        store == "NintendoEShop"
        and "store.nintendo.co.kr" not in product_url
    ):
        raise ValueError(
            "Nintendo KR catalog requires a store.nintendo.co.kr product URL",
        )
    settings = storefront_catalog.config(store)
    game = next(
        (item for item in catalog["games"] if item.get("id") == game_id),
        None,
    )
    if game is None:
        raise ValueError("Canonical game ID does not exist")
    decision = catalog_matcher.evaluate(game, metadata)
    product_id = metadata["productId"]
    product = {
        "store": store,
        "productId": product_id,
        "productUrl": product_url,
        "platforms": metadata.get("platforms", settings["platforms"]),
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }
    preview = {
        **game,
        "matchedProduct": {**product, **metadata},
        "matchDecision": decision,
    }
    for catalog_game in catalog["games"]:
        for existing in catalog_game.get("products", []):
            if existing.get("store") != store or existing.get("productId") != product_id:
                continue
            if catalog_game.get("id") == game_id:
                return catalog, preview
            raise ValueError(f"Store product already belongs to {catalog_game.get('id')}")
    if decision["status"] == "Rejected" or (
        decision["status"] == "NeedsReview" and not acknowledge_review
    ):
        return catalog, preview
    updated_game = dict(game)
    updated_game["platforms"] = list(dict.fromkeys([
        *game.get("platforms", []),
        *product["platforms"],
    ]))
    updated_game["products"] = [*game.get("products", []), product]
    updated_games = [updated_game if item is game else item for item in catalog["games"]]
    return {**catalog, "games": updated_games}, {
        **updated_game,
        "matchedProduct": {**product, **metadata},
        "matchDecision": decision,
    }


def import_game(
    catalog_path: Path,
    raw: bytes,
    store: str,
    product_url: str,
    game_id: str,
    apply: bool,
    acknowledge_review: bool = False,
    database_path: Path | None = None,
) -> dict:
    catalog_storage.validate_catalog(
        json.loads(catalog_path.read_text(encoding="utf-8"))
    )
    metadata = storefront_catalog.verified_product(raw, store, product_url)

    def update(current: dict) -> tuple[dict, dict]:
        updated, game = updated_catalog(
            current,
            store,
            product_url,
            game_id,
            metadata,
            acknowledge_review,
        )
        status = game["matchDecision"]["status"]
        if status == "Rejected":
            raise ValueError("Rejected candidate cannot be imported")
        if status == "NeedsReview" and not acknowledge_review:
            raise ValueError("NeedsReview requires explicit acknowledgement")
        return updated, game

    if apply:
        game, _ = catalog_storage.update_catalog(
            catalog_path,
            update,
            store=store,
            product_id=metadata["productId"],
            game_id=game_id,
            database_path=database_path,
        )
        return game
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    _, game = updated_catalog(
        catalog,
        store,
        product_url,
        game_id,
        metadata,
        acknowledge_review,
    )
    return game


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=sorted(storefront_catalog.STORE_CONFIG), required=True)
    parser.add_argument("--product-url", required=True)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-review", action="store_true")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    try:
        storefront_catalog.product_id_from_url(arguments.store, arguments.product_url)
        raw = arguments.input.read_bytes() if arguments.input else storefront_catalog.fetch_product(
            arguments.store,
            arguments.product_url,
            arguments.timeout,
        )
        game = import_game(
            arguments.catalog,
            raw,
            arguments.store,
            arguments.product_url,
            arguments.game_id,
            arguments.apply,
            arguments.acknowledge_review,
            arguments.database,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(game, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
