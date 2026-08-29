#!/usr/bin/env python3
"""Search Steam Store game candidates by title."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import collect_steam_snapshot as steam


class SearchResultParser(HTMLParser):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.results = []
        self.current = None
        self.in_title = False

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        classes = set(values.get("class", "").split())
        if tag == "a" and "search_result_row" in classes and len(self.results) < self.limit:
            app_id = values.get("data-ds-appid", "")
            if app_id.isdigit():
                self.current = {
                    "store": "Steam",
                    "externalProductId": app_id,
                    "title": "",
                    "productUrl": f"https://store.steampowered.com/app/{app_id}",
                    "platforms": [],
                }
        if self.current is None or tag != "span":
            return
        if "title" in classes:
            self.in_title = True
        platform_names = {"win": "Windows", "mac": "macOS", "linux": "Linux"}
        for class_name, platform in platform_names.items():
            if class_name in classes and platform not in self.current["platforms"]:
                self.current["platforms"].append(platform)

    def handle_data(self, data):
        if self.current is not None and self.in_title:
            self.current["title"] += data.strip()

    def handle_endtag(self, tag):
        if tag == "span":
            self.in_title = False
        if tag == "a" and self.current is not None:
            if self.current["title"]:
                self.results.append(self.current)
            self.current = None


def parse_results(raw: bytes, limit: int = 10) -> list[dict]:
    parser = SearchResultParser(limit)
    parser.feed(raw.decode("utf-8"))
    return parser.results


def search(query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    parameters = urlencode({
        "term": query.strip(),
        "category1": "998",
        "cc": "kr",
        "l": "koreana",
    })
    request = Request(
        f"https://store.steampowered.com/search/?{parameters}",
        headers={"User-Agent": steam.USER_AGENT},
    )
    with urlopen(request, timeout=timeout, context=steam.tls_context()) as response:
        return parse_results(response.read(), limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", default=10, type=int)
    arguments = parser.parse_args()
    print(json.dumps({"candidates": search(arguments.query, arguments.limit)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
