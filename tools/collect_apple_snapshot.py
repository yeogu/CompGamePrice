#!/usr/bin/env python3
"""Collect Apple App Store KR prices using catalog track IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import urlopen

import collect_steam_snapshot as network_support
import apple_product_metadata
import storefront_price_support as support


def apple_targets(catalog: Path) -> list[tuple[str, str]]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    return [
        (product["productId"], game["id"])
        for game in document["games"]
        for product in game.get("products", [])
        if product.get("store") == "AppleAppStore"
    ]


def normalized_row(raw: bytes, track_id: str, game_id: str) -> str:
    document = json.loads(raw)
    if document.get("resultCount") != 1 or len(document.get("results", [])) != 1:
        raise support.PermanentCollectionError(
            f"Apple product {track_id} was not found"
        )
    product = document["results"][0]
    if str(product.get("trackId")) != track_id:
        raise support.PermanentCollectionError("Apple response track ID mismatch")
    if not apple_product_metadata.is_game(product):
        raise support.PermanentCollectionError(
            f"Apple product {track_id} is not categorized as a game"
        )
    if product.get("currency") != "KRW":
        raise support.PermanentCollectionError(
            "REGION_MISMATCH: Apple KR product returned currency "
            f"{product.get('currency') or 'UNKNOWN'}; expected KRW"
        )
    price = product.get("price")
    if not isinstance(price, (int, float)) or price < 0 or int(price) != price:
        raise support.PermanentCollectionError(
            "Apple KRW price must be a non-negative integer"
        )
    families = product.get("supportedDevices", [])
    device_families = []
    if str(product.get("kind", "")).casefold() in {"mac-software", "macsoftware"}:
        device_families.append("MAC")
    if any(str(value).startswith("iPhone") for value in families):
        device_families.append("IPHONE")
    if any(str(value).startswith("iPad") for value in families):
        device_families.append("IPAD")
    if not device_families:
        raise support.PermanentCollectionError(
            "Apple response has no supported Apple platform"
        )
    return f"{track_id},{game_id},{int(price)},{'+'.join(device_families)},true"


def fetch(track_id: str, timeout: float) -> bytes:
    url = f"https://itunes.apple.com/lookup?id={track_id}&country=kr&entity=software"
    with urlopen(
        url,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def collect(
    catalog: Path,
    output: Path,
    product_id: str | None = None,
    timeout: float = 10.0,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    fetcher=fetch,
) -> tuple[int, list[tuple[str, str]]]:
    targets = apple_targets(catalog)
    if product_id is not None:
        targets = [target for target in targets if target[0] == product_id]
        if not targets:
            raise ValueError(f"unknown Apple App Store product: {product_id}")
    collection_targets = [
        (track_id, game_id, "") for track_id, game_id in targets
    ]

    def selected_fetcher(track_id, _game_id, _url, selected_timeout):
        return fetcher(track_id, selected_timeout)

    def selected_normalizer(raw, track_id, game_id, _url):
        return normalized_row(raw, track_id, game_id)

    rows, failures = support.collect_with_retry(
        collection_targets,
        selected_normalizer,
        selected_fetcher,
        timeout,
        max_attempts,
        retry_delay,
        0,
        max_workers=1,
    )
    if rows:
        support.atomic_write_text(
            output,
            "# track_id,canonical_game_id,amount_krw,device_families,available_for_sale\n" +
            "\n".join(rows) + "\n",
        )
    return len(rows), failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output", default=root / "snapshots/latest/apple_app_store_products.csv", type=Path)
    arguments = parser.parse_args()
    collected, failures = collect(arguments.catalog, arguments.output)
    print(f"Collected {collected} Apple products")
    for track_id, error in failures:
        print(f"Failed {track_id}: {error}")
    return 1 if failures or collected == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
