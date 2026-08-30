#!/usr/bin/env python3
"""Preview or attach a verified Google Play game to a canonical catalog game."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

import collect_google_play_snapshot as google_play
import collect_steam_snapshot as network_support


class CatalogImportError(ValueError):
    pass


EXCLUDED_TITLE_WORDS = {
    "guide",
    "walkthrough",
    "wallpaper",
    "soundtrack",
    "demo",
    "companion",
}


def normalized_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def verified_product(raw: bytes, package_name: str) -> dict:
    product = google_play.product_document(raw)
    title = product.get("name")
    category = product.get("applicationCategory")
    operating_system = product.get("operatingSystem")
    if not isinstance(title, str) or not title.strip():
        raise CatalogImportError("Google Play product has no title")
    if not isinstance(category, str) or not category.startswith("GAME"):
        raise CatalogImportError("Only Google Play games can be imported")
    if operating_system != "Android":
        raise CatalogImportError("Google Play product must support Android")
    if normalized_words(title) & EXCLUDED_TITLE_WORDS:
        raise CatalogImportError("Guide, demo, companion, and media apps are excluded")
    block = google_play.normalized_block(raw, package_name, "preview")
    price_micros = int(re.search(r"price_micros=(\d+)", block).group(1))
    if price_micros == 0:
        raise CatalogImportError("Free Google Play apps are not price candidates")
    author = product.get("author")
    developer = author.get("name", "") if isinstance(author, dict) else ""
    return {
        "title": title.strip(),
        "developer": developer,
        "priceMinor": price_micros // 1_000_000,
        "currency": "KRW",
    }


def updated_catalog(catalog: dict, game_id: str, package_name: str, metadata: dict) -> tuple[dict, dict]:
    games = catalog.get("games")
    if catalog.get("schemaVersion") != 4 or not isinstance(games, list):
        raise CatalogImportError("Game catalog requires schemaVersion 4 and games")
    game = next((item for item in games if item.get("id") == game_id), None)
    if game is None:
        raise CatalogImportError("Canonical game ID does not exist")
    existing_words = normalized_words(game.get("title", ""))
    product_words = normalized_words(metadata["title"])
    if existing_words and not existing_words.issubset(product_words):
        raise CatalogImportError("Google Play title does not match the canonical game")
    for catalog_game in games:
        for product in catalog_game.get("products", []):
            if product.get("store") == "GooglePlay" and product.get("productId") == package_name:
                raise CatalogImportError("Google Play package already exists")
    product = {
        "store": "GooglePlay",
        "productId": package_name,
        "productUrl": f"https://play.google.com/store/apps/details?id={package_name}",
        "platforms": ["Android"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }
    updated_game = {**game}
    updated_game["platforms"] = list(dict.fromkeys([*game.get("platforms", []), "Android"]))
    updated_game["products"] = [*game.get("products", []), product]
    updated_games = [updated_game if item is game else item for item in games]
    return {**catalog, "games": updated_games}, {**updated_game, "matchedProduct": {**product, **metadata}}


def import_game(catalog_path: Path, raw: bytes, package_name: str, game_id: str, apply: bool) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", package_name):
        raise CatalogImportError("Invalid Google Play package name")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    metadata = verified_product(raw, package_name)
    updated, game = updated_catalog(catalog, game_id, package_name, metadata)
    if apply:
        backup = catalog_path.with_suffix(catalog_path.suffix + ".bak")
        shutil.copy2(catalog_path, backup)
        network_support.atomic_write(
            catalog_path,
            (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
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
    parser.add_argument("--timeout", default=15.0, type=float)
    arguments = parser.parse_args()
    try:
        raw = arguments.input.read_bytes() if arguments.input else google_play.fetch(arguments.package_name, arguments.timeout)
        game = import_game(
            arguments.catalog,
            raw,
            arguments.package_name,
            arguments.game_id,
            arguments.apply,
        )
    except (CatalogImportError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(game, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
