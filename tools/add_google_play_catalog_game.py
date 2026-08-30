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
    return set(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def normalized_identity(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


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
        "isAndroid": operating_system == "Android",
        "excludedWords": sorted(normalized_words(title) & EXCLUDED_TITLE_WORDS),
    }


def match_decision(game: dict, metadata: dict) -> dict:
    reasons = []
    rejected = False
    if not metadata["isGame"]:
        reasons.append("Google Play category is not a game")
        rejected = True
    if not metadata["isAndroid"]:
        reasons.append("Product does not support Android")
        rejected = True
    if metadata["currency"] != "KRW" or metadata["priceMinor"] <= 0:
        reasons.append("Product is not a paid KRW purchase")
        rejected = True
    if metadata["excludedWords"]:
        reasons.append("Title indicates guide, demo, companion, or media content")
        rejected = True

    product_title = normalized_identity(metadata["title"])
    canonical_titles = [game.get("title", ""), *game.get("aliases", [])]
    title_source = next(
        (
            title
            for title in canonical_titles
            if normalized_identity(title)
            and normalized_identity(title) in product_title
        ),
        "",
    )
    if title_source:
        reasons.append(f'Title matches "{title_source}"')
    else:
        reasons.append("Title does not match the canonical title or aliases")

    canonical_developers = {
        normalized_identity(value)
        for value in game.get("developers", [])
        if normalized_identity(value)
    }
    product_developer = normalized_identity(metadata["developer"])
    developer_matches = bool(
        product_developer and product_developer in canonical_developers
    )
    if developer_matches:
        reasons.append("Developer matches the canonical game")
    elif canonical_developers and product_developer:
        reasons.append("Developer differs from the canonical game")
        rejected = True
    else:
        reasons.append("Developer information is incomplete")

    if rejected or not title_source:
        status = "Rejected"
    elif title_source and developer_matches:
        status = "ApprovedCandidate"
    else:
        status = "NeedsReview"
    return {
        "status": status,
        "reasons": reasons,
        "titleMatchSource": title_source,
        "developerMatched": developer_matches,
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
    decision = match_decision(game, metadata)
    product = {
        "store": "GooglePlay",
        "productId": package_name,
        "productUrl": f"https://play.google.com/store/apps/details?id={package_name}",
        "platforms": ["Android"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }
    if decision["status"] == "Rejected" or (
        decision["status"] == "NeedsReview" and not acknowledge_review
    ):
        return catalog, {
            **game,
            "matchedProduct": {**product, **metadata},
            "matchDecision": decision,
        }
    for catalog_game in games:
        for product in catalog_game.get("products", []):
            if product.get("store") == "GooglePlay" and product.get("productId") == package_name:
                raise CatalogImportError("Google Play package already exists")
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
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", package_name):
        raise CatalogImportError("Invalid Google Play package name")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    metadata = verified_product(raw, package_name)
    updated, game = updated_catalog(
        catalog,
        game_id,
        package_name,
        metadata,
        acknowledge_review,
    )
    decision = game["matchDecision"]["status"]
    if apply and decision == "Rejected":
        raise CatalogImportError("Rejected candidate cannot be imported")
    if apply and decision == "NeedsReview" and not acknowledge_review:
        raise CatalogImportError("NeedsReview requires explicit acknowledgement")
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
    parser.add_argument("--acknowledge-review", action="store_true")
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
            arguments.acknowledge_review,
        )
    except (CatalogImportError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(game, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
