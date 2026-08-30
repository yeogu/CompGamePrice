#!/usr/bin/env python3
"""Collect registered Google Play KR prices into the provider snapshot format."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.request import Request, urlopen

import collect_steam_snapshot as network_support


def google_play_targets(catalog: Path) -> list[tuple[str, str]]:
    document = json.loads(catalog.read_text(encoding="utf-8"))
    return [
        (product["productId"], game["id"])
        for game in document["games"]
        for product in game.get("products", [])
        if product.get("store") == "GooglePlay"
    ]


def product_document(raw: bytes) -> dict:
    page = raw.decode("utf-8")
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for match in matches:
        try:
            candidate = json.loads(html.unescape(match))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("@type") in {
            "SoftwareApplication",
            "MobileApplication",
        }:
            return candidate
    raise ValueError("Google Play response has no application metadata")


def normalized_block(raw: bytes, package_name: str, game_id: str) -> str:
    product = product_document(raw)
    offers = product.get("offers")
    if isinstance(offers, list):
        offer = offers[0] if offers else None
    else:
        offer = offers
    if not isinstance(offer, dict):
        raise ValueError("Google Play response has no purchase offer")
    if offer.get("priceCurrency") != "KRW":
        raise ValueError("Google Play response currency must be KRW")
    try:
        price = int(offer["price"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Google Play KRW price must be an integer") from error
    if price < 0:
        raise ValueError("Google Play KRW price cannot be negative")
    micros = price * 1_000_000
    return "\n".join(
        [
            f"package_name={package_name}",
            f"game_id={game_id}",
            f"price_micros={micros}",
            "published=true",
        ]
    )


def fetch(package_name: str, timeout: float) -> bytes:
    url = (
        "https://play.google.com/store/apps/details"
        f"?id={package_name}&gl=KR&hl=ko"
    )
    request = Request(url, headers={"User-Agent": "CompGamePrice/0.1"})
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def collect(
    catalog: Path,
    output: Path,
    timeout: float = 15.0,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    fetcher=fetch,
) -> tuple[int, list[tuple[str, str]]]:
    blocks = []
    failures = []
    for package_name, game_id in google_play_targets(catalog):
        last_error = ""
        for attempt in range(max_attempts):
            try:
                raw = fetcher(package_name, timeout)
                blocks.append(normalized_block(raw, package_name, game_id))
                break
            except Exception as error:
                last_error = str(error)
                if attempt + 1 < max_attempts:
                    time.sleep(retry_delay * (2**attempt))
        else:
            failures.append((package_name, last_error))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output.parent,
        delete=False,
    ) as temporary:
        temporary.write("# Generated Google Play KR snapshot\n")
        temporary.write("\n\n".join(blocks))
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)
    return len(blocks), failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default=root / "data/game_catalog.json",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default=root / "snapshots/latest/google_play_products.txt",
        type=Path,
    )
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
    arguments = parser.parse_args()
    collected, failures = collect(
        arguments.catalog,
        arguments.output,
        arguments.timeout,
        arguments.max_attempts,
        arguments.retry_delay,
    )
    print(f"Collected {collected} Google Play products")
    for package_name, error in failures:
        print(f"Failed {package_name}: {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
