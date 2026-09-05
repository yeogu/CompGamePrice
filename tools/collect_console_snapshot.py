#!/usr/bin/env python3
"""Collect registered PlayStation or Microsoft Store KR prices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import storefront_catalog
import storefront_price_support as support


SUPPORTED_STORES = {"PlayStationStore", "MicrosoftStore"}
PLATFORM_VALUES = {
    "PlayStation4": "PS4",
    "PlayStation5": "PS5",
    "XboxOne": "XBOX_ONE",
    "XboxSeries": "XBOX_SERIES",
}


def console_targets(catalog: Path, store: str) -> list[tuple[str, str, str]]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    return [
        (product["productId"], game["id"], product["productUrl"])
        for game in document["games"]
        for product in game.get("products", [])
        if product.get("store") == store
    ]


def fetch_for(store: str):
    def fetch(
        product_id: str,
        game_id: str,
        product_url: str,
        timeout: float,
    ) -> bytes:
        del product_id
        del game_id
        return storefront_catalog.fetch_product(store, product_url, timeout)

    return fetch


def normalizer_for(store: str):
    def normalized_row(
        raw: bytes,
        product_id: str,
        game_id: str,
        product_url: str,
    ) -> str:
        try:
            metadata = storefront_catalog.verified_product(
                raw,
                store,
                product_url,
            )
        except ValueError as error:
            raise support.PermanentCollectionError(str(error)) from error
        price = metadata.get("priceMinor")
        currency = metadata.get("currency")
        if price is None:
            raise support.PermanentCollectionError(
                f"{storefront_catalog.config(store)['display']} response has no price",
            )
        if currency != "KRW":
            raise support.PermanentCollectionError("console Store price must be KRW")
        if price < 0:
            raise support.PermanentCollectionError("console Store price cannot be negative")
        platforms = [PLATFORM_VALUES[value] for value in metadata["platforms"]]
        return ",".join([
            product_id,
            game_id,
            str(price),
            str(price),
            "0",
            "|".join(platforms),
            "KR",
            "AVAILABLE",
        ])

    return normalized_row


def collect(
    store: str,
    catalog: Path,
    output: Path,
    timeout: float = 15.0,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    request_delay: float = 1.0,
    fetcher=None,
) -> tuple[int, list[tuple[str, str]]]:
    if store not in SUPPORTED_STORES:
        raise ValueError("unsupported console Store")
    selected_fetcher = fetcher or fetch_for(store)
    rows, failures = support.collect_with_retry(
        console_targets(catalog, store),
        normalizer_for(store),
        selected_fetcher,
        timeout,
        max_attempts,
        retry_delay,
        request_delay,
    )
    if rows:
        support.atomic_write_text(
            output,
            "product_id,game_id,regular_price_krw,current_price_krw,"
            "discount_percent,platforms,country,availability\n" +
            "\n".join(rows) +
            "\n",
        )
    return len(rows), failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, choices=sorted(SUPPORTED_STORES))
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
    parser.add_argument("--request-delay", default=1.0, type=float)
    arguments = parser.parse_args()
    collected, failures = collect(
        arguments.store,
        arguments.catalog,
        arguments.output,
        arguments.timeout,
        arguments.max_attempts,
        arguments.retry_delay,
        arguments.request_delay,
    )
    print(f"Collected {collected} {arguments.store} products")
    for product_id, error in failures:
        print(f"Failed {product_id}: {error}")
    return 1 if failures or collected == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
