#!/usr/bin/env python3
"""Search the Korean Microsoft Store catalog for Xbox games."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import catalog_matcher
import collect_steam_snapshot as network_support


SEARCH_ENDPOINT = "https://emerald.xboxservices.com/xboxcomfd/search/games"
CATALOG_ENDPOINT = "https://displaycatalog.mp.microsoft.com/v7.0/products"
XBOX_PRODUCT_URL = "https://www.xbox.com/ko-KR/games/store/_/{product_id}"
NON_STANDARD_OFFER_WORDS = {
    "addon",
    "addons",
    "bundle",
    "deluxe",
    "dlc",
    "goty",
    "premium",
    "ultimate",
    "upgrade",
    "번들",
    "디럭스",
    "얼티밋",
    "추가",
    "콘텐츠",
    "프리미엄",
}


def fetch_json(url: str, timeout: float) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DealQuest/1.0)",
            "MS-CV": "DealQuest.1",
            "Accept": "application/json",
        },
    )
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return json.load(response)


def platform_names(values: list[str]) -> list[str]:
    platforms = []
    if "XboxOne" in values:
        platforms.append("XboxOne")
    if "XboxSeriesX" in values:
        platforms.append("XboxSeries")
    return platforms


def image_url(images: dict) -> str:
    for key in ("poster", "boxArt", "featurePromotionalSquareArt"):
        image = images.get(key, {})
        if image.get("url"):
            return str(image["url"])
    return ""


def candidate_from_summary(summary: dict) -> dict | None:
    if summary.get("productKind") != "Game":
        return None
    product_id = str(summary.get("productId", "")).strip()
    title = str(summary.get("title", "")).strip()
    platforms = platform_names(summary.get("availableOn", []))
    if not product_id or not title or not platforms:
        return None
    return {
        "store": "Microsoft Store",
        "externalProductId": product_id,
        "title": title,
        "developer": str(summary.get("developerName", "")).strip(),
        "productUrl": XBOX_PRODUCT_URL.format(product_id=product_id),
        "platforms": platforms,
        "imageUrl": image_url(summary.get("images", {})),
    }


def search(query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    parameters = urlencode({"locale": "ko-KR", "Query": query.strip()})
    document = fetch_json(f"{SEARCH_ENDPOINT}?{parameters}", timeout)
    summaries = document.get("productSummaries")
    if not isinstance(summaries, list):
        raise ValueError("Microsoft Store search response is malformed")
    candidates = []
    for summary in summaries:
        candidate = candidate_from_summary(summary)
        if candidate is None:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def fetch_product(product_id: str, timeout: float = 15.0) -> bytes:
    parameters = urlencode({
        "bigIds": product_id,
        "market": "KR",
        "languages": "ko-kr",
    })
    document = fetch_json(f"{CATALOG_ENDPOINT}?{parameters}", timeout)
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def product_platforms(product: dict) -> list[str]:
    properties = product.get("Properties", {})
    generations = set(properties.get("XboxConsoleGenCompatible", []))
    generations.update(properties.get("XboxConsoleGenOptimized", []))
    platforms = []
    if "ConsoleGen8" in generations:
        platforms.append("XboxOne")
    if "ConsoleGen9" in generations:
        platforms.append("XboxSeries")
    return platforms


def purchase_price(product: dict) -> tuple[int | None, str, bool]:
    prices = []
    for sku_availability in product.get("DisplaySkuAvailabilities", []):
        for availability in sku_availability.get("Availabilities", []):
            if "Purchase" not in availability.get("Actions", []):
                continue
            price = availability.get("OrderManagementData", {}).get("Price", {})
            if price.get("CurrencyCode") != "KRW":
                continue
            value = price.get("ListPrice")
            if not isinstance(value, (int, float)) or value < 0:
                continue
            prices.append(int(round(value)))
    paid_prices = [price for price in prices if price > 0]
    if paid_prices:
        return min(paid_prices), "KRW", True
    if prices:
        return 0, "KRW", True
    return None, "", False


def localized_product(product: dict) -> dict:
    localized = product.get("LocalizedProperties", [])
    return localized[0] if localized and isinstance(localized[0], dict) else {}


def localized_image_url(localized: dict) -> str:
    images = localized.get("Images", [])
    for purpose in ("Poster", "BoxArt", "BrandedKeyArt"):
        image = next(
            (item for item in images if item.get("ImagePurpose") == purpose),
            None,
        )
        if image is not None and image.get("Uri"):
            uri = str(image["Uri"])
            return f"https:{uri}" if uri.startswith("//") else uri
    return ""


def verified_product(raw: bytes, product_id: str) -> dict:
    document = json.loads(raw)
    products = document.get("Products")
    if not isinstance(products, list) or not products:
        raise ValueError("Microsoft Store product response is malformed")
    product = products[0]
    localized = localized_product(product)
    title = str(localized.get("ProductTitle", "")).strip()
    if not title:
        raise ValueError("Microsoft Store product has no title")
    platforms = product_platforms(product)
    price_minor, currency, is_purchasable = purchase_price(product)
    return {
        "productId": product_id,
        "title": title,
        "developer": str(localized.get("DeveloperName", "")).strip(),
        "priceMinor": price_minor,
        "currency": currency,
        "allowMissingPrice": False,
        "isGame": product.get("ProductType") == "Game",
        "supportsTargetPlatform": bool(platforms) and is_purchasable,
        "platforms": platforms,
        "imageUrl": localized_image_url(localized),
        "excludedWords": sorted(
            catalog_matcher.normalized_words(title) &
            (catalog_matcher.EXCLUDED_TITLE_WORDS | NON_STANDARD_OFFER_WORDS)
        ),
    }
