#!/usr/bin/env python3
"""Search Google Play game candidates by title."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import collect_steam_snapshot as network_support


class SearchResultParser(HTMLParser):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.results = []
        self.packages = set()

    def handle_starttag(self, tag, attributes):
        if tag != "a" or len(self.results) >= self.limit:
            return
        values = dict(attributes)
        href = values.get("href", "")
        if not href.startswith("/store/apps/details?"):
            return
        package_name = parse_qs(urlparse(href).query).get("id", [""])[0]
        title = values.get("aria-label", "").strip()
        if not package_name or not title or package_name in self.packages:
            return
        self.packages.add(package_name)
        self.results.append(
            {
                "store": "Google Play",
                "externalProductId": package_name,
                "title": title,
                "productUrl": (
                    "https://play.google.com/store/apps/details"
                    f"?id={package_name}&gl=KR&hl=ko"
                ),
                "platforms": ["Android"],
            }
        )


def parse_results(raw: bytes, limit: int = 10) -> list[dict]:
    parser = SearchResultParser(limit)
    parser.feed(raw.decode("utf-8"))
    return parser.results


def search(query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    parameters = urlencode(
        {"q": query.strip(), "c": "apps", "hl": "ko", "gl": "KR"}
    )
    request = Request(
        f"https://play.google.com/store/search?{parameters}",
        headers={"User-Agent": "CompGamePrice/0.1"},
    )
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return parse_results(response.read(), limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", default=10, type=int)
    arguments = parser.parse_args()
    print(
        json.dumps(
            {"candidates": search(arguments.query, arguments.limit)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
