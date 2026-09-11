#!/usr/bin/env python3
"""Search Apple App Store KR game candidates by title."""

from __future__ import annotations

import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen

import collect_steam_snapshot as network_support
import apple_product_metadata


def product_platforms(product: dict) -> list[str]:
    kind = str(product.get("kind", "")).casefold()
    if kind in {"mac-software", "macsoftware"}:
        return ["macOS"]
    supported = product.get("supportedDevices", [])
    platforms = []
    if any(str(value).startswith("iPhone") for value in supported):
        platforms.append("iOS")
    if any(str(value).startswith("iPad") for value in supported):
        platforms.append("iPadOS")
    return platforms


def parse_results(raw: bytes, limit: int = 10) -> list[dict]:
    document = json.loads(raw)
    candidates = []
    for product in document.get("results", []):
        if not apple_product_metadata.is_game(product):
            continue
        track_id = product.get("trackId")
        title = product.get("trackName")
        if not isinstance(track_id, int) or not isinstance(title, str):
            continue
        platforms = product_platforms(product)
        candidate = {
            "store": "Apple App Store",
            "externalProductId": str(track_id),
            "title": title,
            "imageUrl": product.get("artworkUrl512") or product.get("artworkUrl100", ""),
            "developer": product.get("sellerName", ""),
            "currency": product.get("currency", ""),
            "productUrl": product.get(
                "trackViewUrl",
                f"https://apps.apple.com/app/id{track_id}",
            ),
            "platforms": platforms,
        }
        price = product.get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            candidate["priceMinor"] = price
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def search(query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    common = {
            "term": query.strip(),
            "country": "kr",
            "media": "software",
            "limit": limit,
    }
    candidates = []
    seen = set()
    for entity in ("software", "macSoftware"):
        genre_id = (apple_product_metadata.APPLE_MAC_GAMES_GENRE_ID
                    if entity == "macSoftware"
                    else apple_product_metadata.APPLE_GAMES_GENRE_ID)
        parameters = urlencode({**common, "entity": entity, "genreId": genre_id})
        with urlopen(
            f"https://itunes.apple.com/search?{parameters}",
            timeout=timeout,
            context=network_support.tls_context(),
        ) as response:
            results = parse_results(response.read(), limit)
        for candidate in results:
            identity = candidate["externalProductId"]
            if identity not in seen:
                seen.add(identity)
                candidates.append(candidate)
            if len(candidates) >= limit:
                return candidates
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", default=10, type=int)
    arguments = parser.parse_args()
    print(
        json.dumps(
            {"candidates": search(arguments.query, arguments.limit)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
