#!/usr/bin/env python3
"""Collect Apple App Store KR prices using catalog track IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen

import collect_steam_snapshot as network_support


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
        raise ValueError(f"Apple product {track_id} was not found")
    product = document["results"][0]
    if str(product.get("trackId")) != track_id:
        raise ValueError("Apple response track ID mismatch")
    if product.get("currency") != "KRW":
        raise ValueError("Apple response currency must be KRW")
    price = product.get("price")
    if not isinstance(price, (int, float)) or price < 0 or int(price) != price:
        raise ValueError("Apple KRW price must be a non-negative integer")
    families = product.get("supportedDevices", [])
    device_families = []
    if any(str(value).startswith("iPhone") for value in families):
        device_families.append("IPHONE")
    if any(str(value).startswith("iPad") for value in families):
        device_families.append("IPAD")
    if not device_families:
        raise ValueError("Apple response has no supported iPhone or iPad device")
    return f"{track_id},{game_id},{int(price)},{'+'.join(device_families)},true"


def collect(catalog: Path, output: Path) -> int:
    rows = []
    for track_id, game_id in apple_targets(catalog):
        url = f"https://itunes.apple.com/lookup?id={track_id}&country=kr&entity=software"
        with urlopen(
            url,
            timeout=10,
            context=network_support.tls_context(),
        ) as response:
            rows.append(normalized_row(response.read(), track_id, game_id))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as temporary:
        temporary.write("# track_id,canonical_game_id,amount_krw,device_families,available_for_sale\n")
        temporary.write("\n".join(rows) + "\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)
    return len(rows)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output", default=root / "snapshots/latest/apple_app_store_products.csv", type=Path)
    arguments = parser.parse_args()
    print(f"Collected {collect(arguments.catalog, arguments.output)} Apple products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
