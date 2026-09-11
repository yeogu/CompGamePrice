#!/usr/bin/env python3
"""Collect registered Ubisoft Store KR prices from official product pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import storefront_catalog
import storefront_price_support as support


def targets(catalog: Path) -> list[tuple[str, str, str]]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    return [
        (product["productId"], game["id"], product["productUrl"])
        for game in document["games"]
        for product in game.get("products", [])
        if product.get("store") == "UbisoftStore"
    ]


def fetch(product_id: str, game_id: str, product_url: str, timeout: float) -> bytes:
    del product_id, game_id
    return storefront_catalog.fetch_product("UbisoftStore", product_url, timeout)


def normalized_block(raw: bytes, product_id: str, game_id: str, product_url: str) -> str:
    try:
        metadata = storefront_catalog.verified_product(
            raw, "UbisoftStore", product_url)
    except ValueError as error:
        raise support.PermanentCollectionError(str(error)) from error
    price = metadata.get("priceMinor")
    if price is None:
        raise support.PermanentCollectionError("Ubisoft product has no price")
    if metadata.get("currency") != "KRW":
        raise support.PermanentCollectionError("Ubisoft price must be KRW")
    if price < 0:
        raise support.PermanentCollectionError("Ubisoft price cannot be negative")
    return "\n".join([
        f"offer_id: {product_id}",
        f"game_id: {game_id}",
        f"regular_price_krw: {price}",
        f"current_price_krw: {price}",
        "discount_percent: 0",
        "compatible_os: WIN",
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
    blocks, failures = support.collect_with_retry(
        targets(catalog), normalized_block, fetcher, timeout,
        max_attempts, retry_delay, request_delay)
    if blocks:
        support.atomic_write_text(output, "\n\n".join(blocks) + "\n")
    return len(blocks), failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output", default=root / "snapshots/latest/ubisoft_store_products.txt", type=Path)
    arguments = parser.parse_args()
    collected, failures = collect(arguments.catalog, arguments.output)
    print(f"Collected {collected} Ubisoft Store products")
    for product_id, error in failures:
        print(f"Failed {product_id}: {error}")
    return 1 if failures or collected == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
