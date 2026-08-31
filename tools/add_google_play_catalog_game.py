#!/usr/bin/env python3
"""Preview or attach a verified Google Play game to a canonical catalog game."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import collect_google_play_snapshot as google_play
import catalog_matcher
import catalog_storage


class CatalogImportError(ValueError):
    pass


def verified_product(raw: bytes, package_name: str) -> dict:
    product = google_play.product_document(raw)
    title = product.get("name")
    category = product.get("applicationCategory")
    operating_system = product.get("operatingSystem")
    if not isinstance(title, str) or not title.strip():
        raise CatalogImportError("Google Play product has no title")
    offers = product.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    offer = offer if isinstance(offer, dict) else {}
    currency = offer.get("priceCurrency", "")
    try:
        price_minor = int(offer.get("price", -1))
    except (TypeError, ValueError):
        price_minor = -1
    author = product.get("author")
    developer = author.get("name", "") if isinstance(author, dict) else ""
    return {
        "title": title.strip(),
        "developer": developer,
        "priceMinor": price_minor,
        "currency": currency,
        "isGame": isinstance(category, str) and category.startswith("GAME"),
        "supportsTargetPlatform": operating_system == "Android",
        "excludedWords": sorted(
            catalog_matcher.normalized_words(title) &
            catalog_matcher.EXCLUDED_TITLE_WORDS
        ),
    }


def updated_catalog(
    catalog: dict,
    game_id: str,
    package_name: str,
    metadata: dict,
    acknowledge_review: bool = False,
) -> tuple[dict, dict]:
    games = catalog.get("games")
    if catalog.get("schemaVersion") != 4 or not isinstance(games, list):
        raise CatalogImportError("Game catalog requires schemaVersion 4 and games")
    game = next((item for item in games if item.get("id") == game_id), None)
    if game is None:
        raise CatalogImportError("Canonical game ID does not exist")
    decision = catalog_matcher.evaluate(game, metadata)
    product = {
        "store": "GooglePlay",
        "productId": package_name,
        "productUrl": f"https://play.google.com/store/apps/details?id={package_name}",
        "platforms": ["Android"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }
    preview = {
        **game,
        "matchedProduct": {**product, **metadata},
        "matchDecision": decision,
    }
    for catalog_game in games:
        for existing in catalog_game.get("products", []):
            if existing.get("store") != "GooglePlay" or existing.get("productId") != package_name:
                continue
            if catalog_game.get("id") == game_id:
                return catalog, preview
            raise CatalogImportError(
                f"Google Play package already belongs to {catalog_game.get('id')}"
            )
    if decision["status"] == "Rejected" or (
        decision["status"] == "NeedsReview" and not acknowledge_review
    ):
        return catalog, preview
    updated_game = {**game}
    updated_game["platforms"] = list(dict.fromkeys([*game.get("platforms", []), "Android"]))
    updated_game["products"] = [*game.get("products", []), product]
    updated_games = [updated_game if item is game else item for item in games]
    return {
        **catalog,
        "games": updated_games,
    }, {
        **updated_game,
        "matchedProduct": {**product, **metadata},
        "matchDecision": decision,
    }


def import_game(
    catalog_path: Path,
    raw: bytes,
    package_name: str,
    game_id: str,
    apply: bool,
    acknowledge_review: bool = False,
    database_path: Path | None = None,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", package_name):
        raise CatalogImportError("Invalid Google Play package name")
    metadata = verified_product(raw, package_name)
    def update(current: dict) -> tuple[dict, dict]:
        updated, game = updated_catalog(
            current,
            game_id,
            package_name,
            metadata,
            acknowledge_review,
        )
        decision = game["matchDecision"]["status"]
        if decision == "Rejected":
            raise CatalogImportError("Rejected candidate cannot be imported")
        if decision == "NeedsReview" and not acknowledge_review:
            raise CatalogImportError("NeedsReview requires explicit acknowledgement")
        return updated, game
    if apply:
        game, _ = catalog_storage.update_catalog(
            catalog_path,
            update,
            store="GooglePlay",
            product_id=package_name,
            game_id=game_id,
            database_path=database_path,
        )
        return game
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(catalog)
    _, game = updated_catalog(
        catalog,
        game_id,
        package_name,
        metadata,
        acknowledge_review,
    )
    return game


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-review", action="store_true")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    try:
        raw = arguments.input.read_bytes() if arguments.input else google_play.fetch(arguments.package_name, arguments.timeout)
        game = import_game(
            arguments.catalog,
            raw,
            arguments.package_name,
            arguments.game_id,
            arguments.apply,
            arguments.acknowledge_review,
            arguments.database,
        )
    except (CatalogImportError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(game, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
