#!/usr/bin/env python3
"""Collect registered Epic Games Store KR prices into Provider snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import collect_steam_snapshot as network_support
import storefront_price_support as support


ENDPOINT = "https://store.epicgames.com/graphql"
QUERY_HASH = "7d58e12d9dd8cb14c84a3ff18d360bf9f0caa96bf218f2c5fda68ba88d68a437"


def epic_targets(catalog: Path) -> list[tuple[str, str, str]]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    return [
        (product["productId"], game["id"], product["productUrl"])
        for game in document["games"]
        for product in game.get("products", [])
        if product.get("store") == "EpicGamesStore"
    ]


def fetch(product_id: str, game_id: str, product_url: str, timeout: float) -> bytes:
    del game_id
    del product_url
    variables = {
        "allowCountries": "KR",
        "category": "games/edition/base",
        "comingSoon": False,
        "count": 10,
        "country": "KR",
        "keywords": product_id.replace("-", " "),
        "locale": "ko-KR",
        "sortBy": "relevancy",
        "sortDir": "DESC",
        "start": 0,
        "withPrice": True,
        "withPromotions": False,
    }
    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": QUERY_HASH,
        },
    }
    query = urlencode({
        "operationName": "searchStoreQuery",
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(extensions, separators=(",", ":")),
    })
    request = Request(
        f"{ENDPOINT}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "DealQuest/0.1",
        },
    )
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def product_slug(element: dict) -> str:
    mappings = element.get("offerMappings") or element.get("catalogNs", {}).get(
        "mappings",
        [],
    )
    if mappings and isinstance(mappings[0], dict):
        return str(mappings[0].get("pageSlug", "")).strip("/")
    return str(element.get("productSlug") or element.get("urlSlug") or "").split("/")[0]


def normalized_block(
    raw: bytes,
    product_id: str,
    game_id: str,
    product_url: str,
) -> str:
    del product_url
    try:
        document = json.loads(raw)
        elements = document["data"]["Catalog"]["searchStore"]["elements"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise support.PermanentCollectionError(
            "Epic response has no searchable products",
        ) from error
    element = next(
        (candidate for candidate in elements if product_slug(candidate) == product_id),
        None,
    )
    if element is None:
        raise support.PermanentCollectionError(
            f"Epic response does not contain exact product {product_id}",
        )
    categories = {
        category.get("path")
        for category in element.get("categories", [])
        if isinstance(category, dict)
    }
    if "games/edition/base" not in categories:
        raise support.PermanentCollectionError("Epic offer is not a base game")
    try:
        total = element["price"]["totalPrice"]
        currency = total["currencyCode"]
        decimals = total["currencyInfo"]["decimals"]
        regular_raw = total["originalPrice"]
        current_raw = total["discountPrice"]
    except (KeyError, TypeError) as error:
        raise support.PermanentCollectionError("Epic response has no price") from error
    if currency != "KRW" or decimals != 0:
        raise support.PermanentCollectionError("Epic price must be whole KRW")
    if not isinstance(regular_raw, int) or not isinstance(current_raw, int):
        raise support.PermanentCollectionError("Epic KRW prices must be integers")
    if current_raw < 0 or regular_raw < current_raw:
        raise support.PermanentCollectionError("Epic price range is invalid")
    discount = 0
    if regular_raw > 0:
        discount = round((regular_raw - current_raw) * 100 / regular_raw)
    platforms = []
    tag_ids = {str(tag.get("id")) for tag in element.get("tags", [])}
    if "9547" in tag_ids or not tag_ids:
        platforms.append("WIN")
    if "10719" in tag_ids:
        platforms.append("MAC")
    if not platforms:
        raise support.PermanentCollectionError("Epic product has no PC platform")
    return "\n".join([
        f"offer_id: {product_id}",
        f"game_id: {game_id}",
        f"regular_price_krw: {regular_raw}",
        f"current_price_krw: {current_raw}",
        f"discount_percent: {discount}",
        f"compatible_os: {'|'.join(platforms)}",
        "status: ACTIVE",
    ])


def collect(
    catalog: Path,
    output: Path,
    timeout: float = 15.0,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    request_delay: float = 1.0,
    fetcher=fetch,
) -> tuple[int, list[tuple[str, str]]]:
    rows, failures = support.collect_with_retry(
        epic_targets(catalog),
        normalized_block,
        fetcher,
        timeout,
        max_attempts,
        retry_delay,
        request_delay,
    )
    if rows:
        support.atomic_write_text(
            output,
            "# Generated Epic Games Store KR snapshot\n" +
            "\n\n".join(rows) +
            "\n",
        )
    return len(rows), failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output", default=root / "snapshots/latest/epic_games_products.txt", type=Path)
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
    parser.add_argument("--request-delay", default=1.0, type=float)
    arguments = parser.parse_args()
    collected, failures = collect(
        arguments.catalog,
        arguments.output,
        arguments.timeout,
        arguments.max_attempts,
        arguments.retry_delay,
        arguments.request_delay,
    )
    print(f"Collected {collected} Epic Games products")
    for product_id, error in failures:
        print(f"Failed {product_id}: {error}")
    return 1 if failures or collected == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
