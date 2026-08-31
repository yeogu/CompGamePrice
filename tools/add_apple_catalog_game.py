#!/usr/bin/env python3
"""Preview or attach a verified Apple App Store game to a canonical game."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.request import urlopen

import catalog_matcher
import catalog_storage
import collect_steam_snapshot as network_support


class CatalogImportError(ValueError):
    pass


def apple_product(raw: bytes, track_id: str) -> dict:
    document = json.loads(raw)
    results = document.get("results", [])
    if document.get("resultCount") != 1 or len(results) != 1:
        raise CatalogImportError("Apple product was not found")
    product = results[0]
    if str(product.get("trackId")) != track_id:
        raise CatalogImportError("Apple response Track ID mismatch")
    title = product.get("trackName")
    if not isinstance(title, str) or not title.strip():
        raise CatalogImportError("Apple product has no title")
    price = product.get("price")
    price_minor = int(price) if isinstance(price, (int, float)) and int(price) == price else -1
    supported = product.get("supportedDevices", [])
    platforms = []
    if any(str(value).startswith("iPhone") for value in supported):
        platforms.append("iOS")
    if any(str(value).startswith("iPad") for value in supported):
        platforms.append("iPadOS")
    genres = {str(value).casefold() for value in product.get("genres", [])}
    primary_genre = str(product.get("primaryGenreName", "")).casefold()
    is_game = primary_genre in {"games", "게임"} or bool(genres & {"games", "게임"})
    return {
        "title": title.strip(),
        "developer": str(product.get("sellerName") or product.get("artistName") or ""),
        "priceMinor": price_minor,
        "currency": str(product.get("currency", "")),
        "isGame": is_game,
        "supportsTargetPlatform": bool(platforms),
        "excludedWords": sorted(
            catalog_matcher.normalized_words(title) &
            catalog_matcher.EXCLUDED_TITLE_WORDS
        ),
        "platforms": platforms,
    }


def updated_catalog(
    catalog: dict,
    game_id: str,
    track_id: str,
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
        "store": "AppleAppStore",
        "productId": track_id,
        "productUrl": f"https://apps.apple.com/app/id{track_id}",
        "platforms": metadata["platforms"],
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
            if existing.get("store") != "AppleAppStore" or existing.get("productId") != track_id:
                continue
            if catalog_game.get("id") == game_id:
                return catalog, preview
            raise CatalogImportError(
                f"Apple Track ID already belongs to {catalog_game.get('id')}"
            )
    if decision["status"] == "Rejected" or (
        decision["status"] == "NeedsReview" and not acknowledge_review
    ):
        return catalog, preview
    updated_game = {**game}
    updated_game["platforms"] = list(
        dict.fromkeys([*game.get("platforms", []), *metadata["platforms"]])
    )
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
    track_id: str,
    game_id: str,
    apply: bool,
    acknowledge_review: bool = False,
    database_path: Path | None = None,
) -> dict:
    if not track_id.isdigit():
        raise CatalogImportError("Apple Track ID must be numeric")
    metadata = apple_product(raw, track_id)
    def update(current: dict) -> tuple[dict, dict]:
        updated, game = updated_catalog(
            current,
            game_id,
            track_id,
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
            store="AppleAppStore",
            product_id=track_id,
            game_id=game_id,
            database_path=database_path,
        )
        return game
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(catalog)
    _, game = updated_catalog(
        catalog,
        game_id,
        track_id,
        metadata,
        acknowledge_review,
    )
    return game


def fetch(track_id: str, timeout: float) -> bytes:
    url = f"https://itunes.apple.com/lookup?id={track_id}&country=kr&entity=software"
    with urlopen(
        url,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-id", required=True)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-review", action="store_true")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    try:
        raw = arguments.input.read_bytes() if arguments.input else fetch(arguments.track_id, arguments.timeout)
        game = import_game(
            arguments.catalog,
            raw,
            arguments.track_id,
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
