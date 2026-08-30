#!/usr/bin/env python3
"""Search Apple App Store KR game candidates by title."""

from __future__ import annotations

import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen

import collect_steam_snapshot as network_support


def parse_results(raw: bytes, limit: int = 10) -> list[dict]:
    document = json.loads(raw)
    candidates = []
    for product in document.get("results", []):
        track_id = product.get("trackId")
        title = product.get("trackName")
        if not isinstance(track_id, int) or not isinstance(title, str):
            continue
        supported = product.get("supportedDevices", [])
        platforms = []
        if any(str(value).startswith("iPhone") for value in supported):
            platforms.append("iOS")
        if any(str(value).startswith("iPad") for value in supported):
            platforms.append("iPadOS")
        candidates.append(
            {
                "store": "Apple App Store",
                "externalProductId": str(track_id),
                "title": title,
                "developer": product.get("sellerName", ""),
                "priceMinor": product.get("price"),
                "currency": product.get("currency", ""),
                "productUrl": product.get(
                    "trackViewUrl",
                    f"https://apps.apple.com/app/id{track_id}",
                ),
                "platforms": platforms,
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def search(query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    parameters = urlencode(
        {
            "term": query.strip(),
            "country": "kr",
            "media": "software",
            "entity": "software",
            "limit": limit,
        }
    )
    with urlopen(
        f"https://itunes.apple.com/search?{parameters}",
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return parse_results(response.read(), limit)


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
