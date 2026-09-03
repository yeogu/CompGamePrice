#!/usr/bin/env python3
"""Search Nintendo eShop Korea candidates by title."""

import argparse
import json

import storefront_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", default=10, type=int)
    arguments = parser.parse_args()
    candidates = storefront_catalog.search(
        "NintendoEShop",
        arguments.query,
        arguments.limit,
    )
    print(json.dumps({"candidates": candidates}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
