#!/usr/bin/env python3
"""Preview or add one verified Steam base game to the unified catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import catalog_storage
import collect_steam_snapshot as steam


class CatalogImportError(ValueError):
    pass


GENRE_MAPPING = {
    "action": "Action",
    "액션": "Action",
    "adventure": "Adventure",
    "어드벤처": "Adventure",
    "rpg": "RPG",
    "롤 플레잉": "RPG",
    "simulation": "Simulation",
    "시뮬레이션": "Simulation",
    "strategy": "Strategy",
    "전략": "Strategy",
    "sports": "Sports",
    "스포츠": "Sports",
    "racing": "Racing",
    "레이싱": "Racing",
    "casual": "Casual",
    "캐주얼": "Casual",
    "indie": "Indie",
    "인디": "Indie",
    "massively multiplayer": "MMO",
    "대규모 멀티플레이어": "MMO",
}

CATEGORY_TAG_MAPPING = {
    "multi-player": "Multiplayer",
    "멀티플레이어": "Multiplayer",
    "co-op": "Co-op",
    "협동": "Co-op",
    "cross-platform multiplayer": "Cross-Platform",
    "플랫폼간 멀티플레이어": "Cross-Platform",
    "full controller support": "Controller",
    "컨트롤러 완벽 지원": "Controller",
}


def mapped_descriptions(entries, mapping: dict[str, str]) -> list[str]:
    result = []
    for entry in entries if isinstance(entries, list) else []:
        description = entry.get("description") if isinstance(entry, dict) else None
        mapped = mapping.get(description.casefold()) if isinstance(description, str) else None
        if mapped and mapped not in result:
            result.append(mapped)
    return result


def canonical_id(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not value or re.search(r"[a-z]", value) is None:
        raise CatalogImportError("Steam title cannot produce a canonical game id")
    return value


def catalog_game(raw: bytes, app_id: str, game_id: str | None = None) -> dict:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CatalogImportError("Steam returned malformed JSON") from error
    envelope = payload.get(app_id)
    if not isinstance(envelope, dict) or envelope.get("success") is not True:
        raise CatalogImportError(f"Steam returned no successful data for app {app_id}")
    data = envelope.get("data")
    if not isinstance(data, dict) or data.get("steam_appid") != int(app_id):
        raise CatalogImportError("Steam response contains an unexpected app id")
    if data.get("type") != "game":
        raise CatalogImportError("Only Steam base games can be imported")
    if data.get("is_free") is True:
        raise CatalogImportError("Free Steam games are not price-comparison candidates")
    title = data.get("name")
    if not isinstance(title, str) or not title.strip():
        raise CatalogImportError("Steam game has no title")
    platform_data = data.get("platforms")
    if not isinstance(platform_data, dict):
        raise CatalogImportError("Steam game has no platform data")
    platform_names = {
        "windows": "Windows",
        "mac": "macOS",
        "linux": "Linux",
    }
    platforms = [
        public_name
        for steam_name, public_name in platform_names.items()
        if platform_data.get(steam_name) is True
    ]
    if not platforms:
        raise CatalogImportError("Steam game has no supported PC platform")
    resolved_game_id = game_id or canonical_id(title)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", resolved_game_id):
        raise CatalogImportError(
            "Canonical game id must contain lowercase letters, numbers, and hyphens"
        )
    return {
        "id": resolved_game_id,
        "title": title.strip(),
        "imageUrl": str(data.get("header_image", "")).strip(),
        "aliases": [],
        "developers": [
            value.strip()
            for value in data.get("developers", [])
            if isinstance(value, str) and value.strip()
        ],
        "publishers": [
            value.strip()
            for value in data.get("publishers", [])
            if isinstance(value, str) and value.strip()
        ],
        "platforms": platforms,
        "genres": mapped_descriptions(data.get("genres"), GENRE_MAPPING),
        "tags": mapped_descriptions(data.get("categories"), CATEGORY_TAG_MAPPING),
        "products": [
            {
                "store": "Steam",
                "productId": app_id,
                "productUrl": f"https://store.steampowered.com/app/{app_id}",
                "platforms": platforms,
                "region": "KR",
                "edition": "Standard",
                "offerType": "BaseGame",
            }
        ],
    }


def updated_catalog(catalog: dict, game: dict) -> dict:
    if catalog.get("schemaVersion") != 4 or not isinstance(catalog.get("games"), list):
        raise CatalogImportError("Game catalog requires schemaVersion 4 and games")
    for existing in catalog["games"]:
        for product in existing.get("products", []):
            if product.get("store") != "Steam" or product.get("productId") != game["products"][0]["productId"]:
                continue
            if existing.get("id") == game["id"]:
                return catalog
            raise CatalogImportError(
                f"Steam product already belongs to {existing.get('id')}: {game['products'][0]['productId']}"
            )
        if existing.get("id") == game["id"]:
            raise CatalogImportError(f"Canonical game id already exists: {game['id']}")
        if existing.get("title", "").casefold() == game["title"].casefold():
            raise CatalogImportError(f"Game title already exists: {game['title']}")
    return {**catalog, "games": [*catalog["games"], game]}


def load_catalog(catalog_path: Path) -> dict:
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def import_game(
    catalog_path: Path,
    raw: bytes,
    app_id: str,
    apply: bool,
    game_id: str | None = None,
    database_path: Path | None = None,
) -> dict:
    if not app_id.isdigit():
        raise CatalogImportError("Steam app id must be numeric")
    game = catalog_game(raw, app_id, game_id)
    if apply:
        def update(current: dict) -> tuple[dict, dict]:
            return updated_catalog(current, game), game
        result, _ = catalog_storage.update_catalog(
            catalog_path,
            update,
            store="Steam",
            product_id=app_id,
            game_id=game["id"],
            database_path=database_path,
        )
        return result
    catalog = load_catalog(catalog_path)
    catalog_storage.validate_catalog(catalog)
    updated_catalog(catalog, game)
    return game


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--game-id")
    parser.add_argument("--input", type=Path, help="Use a saved Steam response for testing")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    if arguments.input:
        raw = arguments.input.read_bytes()
    else:
        raw, _, _ = steam.fetch(arguments.app_id, "kr", "korean", arguments.timeout)
    try:
        game = import_game(
            arguments.catalog,
            raw,
            arguments.app_id,
            arguments.apply,
            arguments.game_id,
            arguments.database,
        )
    except (CatalogImportError, json.JSONDecodeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(game, ensure_ascii=False, indent=2))
    print("Catalog updated." if arguments.apply else "Preview only; use --apply to update the catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
