#!/usr/bin/env python3
"""Collect registered Nintendo eShop KR prices into Provider snapshots."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

import collect_steam_snapshot as network_support
import storefront_price_support as support


class NintendoPriceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.json_ld: list[dict] = []
        self.in_json_ld = False
        self.json_text: list[str] = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "meta":
            key = values.get("itemprop") or values.get("property")
            content = values.get("content")
            if key and content:
                self.meta[key] = content
        if tag == "script" and values.get("type") == "application/ld+json":
            self.in_json_ld = True
            self.json_text = []

    def handle_data(self, data):
        if self.in_json_ld:
            self.json_text.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or not self.in_json_ld:
            return
        self.in_json_ld = False
        try:
            document = json.loads("".join(self.json_text))
        except json.JSONDecodeError:
            return
        if isinstance(document, dict):
            self.json_ld.append(document)


def nintendo_targets(catalog: Path) -> list[tuple[str, str, str]]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    return [
        (product["productId"], game["id"], product["productUrl"])
        for game in document["games"]
        for product in game.get("products", [])
        if product.get("store") == "NintendoEShop"
    ]


def korean_product_url(product_id: str, product_url: str) -> str:
    if "store.nintendo.co.kr" in product_url:
        return product_url
    if not product_id.isdigit():
        raise support.PermanentCollectionError(
            "Nintendo KR collection requires a numeric NSUID",
        )
    return f"https://store.nintendo.co.kr/{product_id}"


def fetch(product_id: str, game_id: str, product_url: str, timeout: float) -> bytes:
    del game_id
    url = korean_product_url(product_id, product_url)
    request = Request(
        url,
        headers={
            "Accept-Language": "ko-KR,ko;q=0.9",
            "User-Agent": "DealQuest/0.1",
        },
    )
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def normalized_row(
    raw: bytes,
    product_id: str,
    game_id: str,
    product_url: str,
) -> str:
    del product_url
    parser = NintendoPriceParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    currency = parser.meta.get("priceCurrency", "")
    price_text = parser.meta.get("price", "")
    if not price_text:
        for document in parser.json_ld:
            offer = document.get("offers")
            if isinstance(offer, dict) and offer.get("price") is not None:
                price_text = str(offer["price"])
                currency = str(offer.get("priceCurrency", currency))
                break
    if currency != "KRW":
        raise support.PermanentCollectionError("Nintendo price must be KRW")
    normalized_price = re.sub(r"[^0-9]", "", price_text)
    if not normalized_price:
        raise support.PermanentCollectionError("Nintendo response has no price")
    price = int(normalized_price)
    if price < 0:
        raise support.PermanentCollectionError("Nintendo price cannot be negative")
    return ",".join([
        product_id,
        game_id,
        str(price),
        str(price),
        "0",
        "SWITCH",
        "KR",
        "AVAILABLE",
        "SUPPORTED",
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
        nintendo_targets(catalog),
        normalized_row,
        fetcher,
        timeout,
        max_attempts,
        retry_delay,
        request_delay,
    )
    if rows:
        support.atomic_write_text(
            output,
            "nsuid,game_id,regular_price_krw,current_price_krw,"
            "discount_percent,system,country,availability,"
            "switch2_compatibility\n" +
            "\n".join(rows) +
            "\n",
        )
    return len(rows), failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--output", default=root / "snapshots/latest/nintendo_eshop_products.csv", type=Path)
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
    print(f"Collected {collected} Nintendo eShop products")
    for product_id, error in failures:
        print(f"Failed {product_id}: {error}")
    return 1 if failures or collected == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
