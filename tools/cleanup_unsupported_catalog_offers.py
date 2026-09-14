#!/usr/bin/env python3
"""Audit or remove confidently identified demo, trial, and friend-pass offers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import catalog_storage
import remove_catalog_product
import storefront_catalog


UNSUPPORTED_PATTERN = re.compile(
    r"(?:friend(?:'s)?[\s_-]*pass|친구\s*패스|무료\s*체험판|"
    r"(?:^|[\s_:/-])(?:demo|trial|playtest)(?:$|[\s_:/-])|데모|체험판)",
    re.IGNORECASE,
)


def local_reason(product: dict) -> str | None:
    inspected = " ".join(str(product.get(field, "")) for field in (
        "productId", "productUrl", "offerName",
    ))
    if UNSUPPORTED_PATTERN.search(inspected):
        return "상품 식별자 또는 이름이 Demo·Trial·Friend Pass로 확인됨"
    return None


def audit(
    document: dict,
    verify_playstation: bool = False,
    timeout: float = 15.0,
) -> dict:
    findings = []
    verification_errors = []
    for game in document.get("games", []):
        for product in game.get("products", []):
            reason = local_reason(product)
            store = product.get("store", "")
            product_url = product.get("productUrl", "")
            if (
                reason is None and verify_playstation and
                store == "PlayStationStore" and product_url
            ):
                try:
                    raw = storefront_catalog.fetch_product(
                        store, product_url, timeout=timeout,
                    )
                    storefront_catalog.verified_product(raw, store, product_url)
                except ValueError as error:
                    if "demo or friend-pass" in str(error):
                        reason = "공식 PlayStation 상품이 Demo 또는 Friend Pass로 확인됨"
                    else:
                        verification_errors.append({
                            "gameId": game.get("id", ""),
                            "productId": product.get("productId", ""),
                            "error": str(error),
                        })
                except OSError as error:
                    verification_errors.append({
                        "gameId": game.get("id", ""),
                        "productId": product.get("productId", ""),
                        "error": str(error),
                    })
            if reason:
                findings.append({
                    "gameId": game.get("id", ""),
                    "gameTitle": game.get("title", ""),
                    "store": store,
                    "productId": product.get("productId", ""),
                    "productUrl": product_url,
                    "reason": reason,
                })
    return {
        "checkedProducts": sum(
            len(game.get("products", [])) for game in document.get("games", [])
        ),
        "unsupportedCount": len(findings),
        "unsupported": findings,
        "verificationErrors": verification_errors,
    }


def cleanup(
    catalog_path: Path,
    database_path: Path,
    apply: bool,
    verify_playstation: bool = False,
    timeout: float = 15.0,
) -> dict:
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(document)
    result = audit(document, verify_playstation, timeout)
    result["applied"] = False
    result["removed"] = []
    if not apply:
        return result
    for finding in result["unsupported"]:
        removed = remove_catalog_product.remove_product(
            catalog_path,
            database_path,
            finding["store"],
            finding["productId"],
            True,
        )
        result["removed"].append(removed)
    result["applied"] = True
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", default=root / "data/game_catalog.json", type=Path,
    )
    parser.add_argument(
        "--database", default=root / "build/game_prices.db", type=Path,
    )
    parser.add_argument("--verify-playstation", action="store_true")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        result = cleanup(
            arguments.catalog,
            arguments.database,
            arguments.apply,
            arguments.verify_playstation,
            arguments.timeout,
        )
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
