#!/usr/bin/env python3
"""Preview or add one verified Steam base game to the unified catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

import collect_steam_snapshot as steam


class CatalogImportError(ValueError):
    pass


def canonical_id(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not value:
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
        "platforms": platforms,
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
        if existing.get("id") == game["id"]:
            raise CatalogImportError(f"Canonical game id already exists: {game['id']}")
        if existing.get("title", "").casefold() == game["title"].casefold():
            raise CatalogImportError(f"Game title already exists: {game['title']}")
        for product in existing.get("products", []):
            if product.get("store") == "Steam" and product.get("productId") == game["products"][0]["productId"]:
                raise CatalogImportError(
                    f"Steam product already exists: {game['products'][0]['productId']}"
                )
    return {**catalog, "games": [*catalog["games"], game]}


def load_catalog(catalog_path: Path) -> dict:
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def write_catalog(catalog_path: Path, catalog: dict) -> None:
    backup = catalog_path.with_suffix(catalog_path.suffix + ".bak")
    shutil.copy2(catalog_path, backup)
    steam.atomic_write(
        catalog_path,
        (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    try:
        steam.load_steam_targets(catalog_path)
    except Exception:
        shutil.copy2(backup, catalog_path)
        raise


def import_game(
    catalog_path: Path,
    raw: bytes,
    app_id: str,
    apply: bool,
    game_id: str | None = None,
) -> dict:
    if not app_id.isdigit():
        raise CatalogImportError("Steam app id must be numeric")
    catalog = load_catalog(catalog_path)
    game = catalog_game(raw, app_id, game_id)
    updated = updated_catalog(catalog, game)
    if apply:
        write_catalog(catalog_path, updated)
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
        )
    except (CatalogImportError, json.JSONDecodeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(game, ensure_ascii=False, indent=2))
    print("Catalog updated." if arguments.apply else "Preview only; use --apply to update the catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
