#!/usr/bin/env python3
"""Search a configured public storefront by title."""

from __future__ import annotations

import argparse
import json

import storefront_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, choices=sorted(storefront_catalog.STORE_CONFIG))
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", default=10, type=int)
    arguments = parser.parse_args()
    print(json.dumps({"candidates": storefront_catalog.search(
        arguments.store, arguments.query, arguments.limit)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
