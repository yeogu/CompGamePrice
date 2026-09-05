#!/usr/bin/env python3
"""Search the Korean PlayStation Store PS4/PS5 catalog."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import catalog_matcher
import collect_steam_snapshot as network_support


ENDPOINT = "https://web.np.playstation.com/api/graphql/v1/op"
CATEGORY_QUERY_HASH = "4ce7d410a4db2c8b635a48c1dcec375906ff63b19dadd87e073f8fd0c0481d35"
PRODUCT_QUERY_HASH = "a128042177bd93dd831164103d53b73ef790d56f51dae647064cb8f9d9fc9d1a"
CATEGORIES = {
    "PlayStation4": "44d8bb20-653e-431e-8ad0-c0a365f68d2f",
    "PlayStation5": "4cbf39e2-5749-4970-ba81-93a489e4570c",
}
PAGE_SIZE = 1000
MAX_PAGES_PER_CATEGORY = 10
IMAGE_ROLES = ("MASTER", "EDITION_KEY_ART", "GAMEHUB_COVER_ART")


def graphql_url(operation: str, variables: dict, query_hash: str) -> str:
    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": query_hash,
        },
    }
    parameters = urlencode({
        "operationName": operation,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(extensions, separators=(",", ":")),
    })
    return f"{ENDPOINT}?{parameters}"


def fetch_json(url: str, timeout: float) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DealQuest/1.0)",
            "Content-Type": "application/json",
            "x-psn-store-locale-override": "ko-kr",
        },
    )
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return json.load(response)


def fetch_category_page(
    category_id: str,
    offset: int,
    timeout: float,
) -> dict:
    variables = {
        "id": category_id,
        "pageArgs": {
            "size": PAGE_SIZE,
            "offset": offset,
        },
        "sortBy": {
            "name": "productName",
            "isAscending": True,
        },
        "filterBy": [],
        "facetOptions": [],
    }
    url = graphql_url("categoryGridRetrieve", variables, CATEGORY_QUERY_HASH)
    document = fetch_json(url, timeout)
    grid = document.get("data", {}).get("categoryGridRetrieve")
    if not isinstance(grid, dict):
        raise ValueError("PlayStation catalog response is malformed")
    return grid


def fetch_product(product_id: str, timeout: float = 15.0) -> bytes:
    variables = {"productId": product_id}
    url = graphql_url("metGetProductById", variables, PRODUCT_QUERY_HASH)
    return json.dumps(fetch_json(url, timeout), ensure_ascii=False).encode("utf-8")


def image_url(product: dict) -> str:
    images = [
        item
        for item in product.get("media", [])
        if item.get("type") == "IMAGE" and item.get("url")
    ]
    for role in IMAGE_ROLES:
        matching = next((item for item in images if item.get("role") == role), None)
        if matching is not None:
            return str(matching["url"])
    return str(images[0]["url"]) if images else ""


def platform_names(values: list[str]) -> list[str]:
    names = []
    if "PS4" in values:
        names.append("PlayStation4")
    if "PS5" in values:
        names.append("PlayStation5")
    return names


def candidate_from_product(product: dict) -> dict | None:
    if product.get("storeDisplayClassification") != "FULL_GAME":
        return None
    product_id = str(product.get("id", "")).strip()
    title = str(product.get("name", "")).strip()
    platforms = platform_names(product.get("platforms", []))
    if not product_id or not title or not platforms:
        return None
    return {
        "store": "PlayStation Store",
        "externalProductId": product_id,
        "title": title,
        "productUrl": f"https://store.playstation.com/ko-kr/product/{product_id}",
        "platforms": platforms,
        "imageUrl": image_url(product),
    }


def merge_candidate(existing: dict, candidate: dict) -> None:
    existing["platforms"] = list(dict.fromkeys([
        *existing.get("platforms", []),
        *candidate.get("platforms", []),
    ]))
    if not existing.get("imageUrl") and candidate.get("imageUrl"):
        existing["imageUrl"] = candidate["imageUrl"]


def load_catalog(timeout: float, page_fetcher=fetch_category_page) -> list[dict]:
    candidates: dict[str, dict] = {}
    for category_id in CATEGORIES.values():
        offset = 0
        for _ in range(MAX_PAGES_PER_CATEGORY):
            page = page_fetcher(category_id, offset, timeout)
            for product in page.get("products", []):
                candidate = candidate_from_product(product)
                if candidate is None:
                    continue
                product_id = candidate["externalProductId"]
                if product_id in candidates:
                    merge_candidate(candidates[product_id], candidate)
                else:
                    candidates[product_id] = candidate
            page_info = page.get("pageInfo", {})
            if page_info.get("isLast"):
                break
            page_size = int(page_info.get("size", PAGE_SIZE))
            offset += page_size
            if offset >= int(page_info.get("totalCount", 0)):
                break
        else:
            raise ValueError("PlayStation catalog exceeded the bounded page limit")
    return list(candidates.values())


def candidate_score(query: str, candidate: dict) -> tuple[int, float, str]:
    normalized_query = catalog_matcher.normalized_identity(query)
    normalized_title = catalog_matcher.normalized_identity(candidate["title"])
    contains = int(normalized_query in normalized_title)
    similarity = SequenceMatcher(None, normalized_query, normalized_title).ratio()
    return contains, similarity, normalized_title


class PlayStationCatalogSearch:
    def __init__(self, loader=load_catalog):
        self.loader = loader
        self.catalog: list[dict] | None = None

    def search(self, query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
        if not query.strip():
            raise ValueError("search query is required")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        if self.catalog is None:
            self.catalog = self.loader(timeout)
        scored = [
            (candidate_score(query, candidate), candidate)
            for candidate in self.catalog
        ]
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)
        return [
            candidate
            for score, candidate in ranked
            if score[0] or score[1] >= 0.65
        ][:limit]


SEARCH = PlayStationCatalogSearch()


def search(query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    return SEARCH.search(query, limit, timeout)


def price_minor(price: dict) -> int | None:
    if price.get("isFree"):
        return 0
    value = str(price.get("discountedPrice", ""))
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def verified_product(raw: bytes, product_id: str) -> dict:
    document = json.loads(raw)
    product = document.get("data", {}).get("productRetrieve")
    if not isinstance(product, dict):
        raise ValueError("PlayStation product response is malformed")
    title = str(product.get("name", "")).strip()
    if not title:
        raise ValueError("PlayStation product has no title")
    price = product.get("price")
    price = price if isinstance(price, dict) else {}
    current_price = price_minor(price)
    platforms = platform_names(product.get("platforms", []))
    classification = product.get("storeDisplayClassification")
    is_subscription = bool(price.get("isTiedToSubscription"))
    return {
        "productId": product_id,
        "title": title,
        "developer": str(product.get("publisherName", "")).strip(),
        "priceMinor": current_price,
        "currency": "KRW" if current_price is not None else "",
        "allowMissingPrice": current_price is None,
        "isGame": product.get("topCategory") == "GAME" and classification == "FULL_GAME",
        "supportsTargetPlatform": bool(platforms) and not is_subscription,
        "platforms": platforms,
        "imageUrl": image_url(product),
        "excludedWords": sorted(
            catalog_matcher.normalized_words(title) &
            catalog_matcher.EXCLUDED_TITLE_WORDS
        ),
    }
