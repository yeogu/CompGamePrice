"""Shared HTML discovery and product parsing for console/PC storefronts."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

import catalog_matcher
import collect_steam_snapshot as network_support


STORE_CONFIG = {
    "EpicGamesStore": {
        "display": "Epic Games Store",
        "hosts": ["store.epicgames.com"],
        "search": "https://store.epicgames.com/ko/browse",
        "searchParameters": {
            "sortBy": "relevancy",
            "sortDir": "DESC",
            "category": "Game",
            "count": "40",
        },
        "productPath": "/p/",
        "platforms": ["Windows"],
    },
    "NintendoEShop": {
        "display": "Nintendo eShop",
        "hosts": ["store.nintendo.co.kr", "www.nintendo.com"],
        "search": "https://store.nintendo.co.kr/catalogsearch/result/",
        "searchParameters": {},
        "productPath": "/",
        "platforms": ["NintendoSwitch"],
    },
}


def config(store: str) -> dict:
    try:
        return STORE_CONFIG[store]
    except KeyError as error:
        raise ValueError("unsupported storefront") from error


def product_id_from_url(store: str, product_url: str) -> str:
    settings = config(store)
    parsed = urlparse(product_url)
    if parsed.hostname not in settings["hosts"]:
        raise ValueError(
            "product URL must use " + " or ".join(settings["hosts"])
        )
    parts = [part for part in parsed.path.split("/") if part]
    if store == "EpicGamesStore":
        try:
            marker = parts.index("p")
            return parts[marker + 1]
        except (ValueError, IndexError) as error:
            raise ValueError("invalid Epic Games product URL") from error
    if not parts:
        raise ValueError("invalid Nintendo eShop product URL")
    identifier = parts[-1].removesuffix(".html")
    is_korean_product = parsed.hostname == "store.nintendo.co.kr" and (
        identifier.isdigit() or parsed.path.endswith(".html")
    )
    is_global_product = parsed.hostname == "www.nintendo.com" and (
        "products" in parts
    )
    if not is_korean_product and not is_global_product:
        raise ValueError("invalid Nintendo eShop product URL")
    return identifier


class StoreSearchParser(HTMLParser):
    def __init__(self, store: str, limit: int):
        super().__init__()
        self.store = store
        self.limit = limit
        self.results: list[dict] = []
        self.identifiers: set[str] = set()
        self.current: dict | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag, attributes):
        if tag != "a" or len(self.results) >= self.limit:
            return
        values = dict(attributes)
        href = values.get("href", "")
        url = urljoin(config(self.store)["search"], href)
        try:
            identifier = product_id_from_url(self.store, url)
        except ValueError:
            return
        if identifier in self.identifiers:
            return
        self.current = {
            "store": config(self.store)["display"],
            "externalProductId": identifier,
            "title": values.get("aria-label", "") or values.get("title", ""),
            "productUrl": url,
            "platforms": config(self.store)["platforms"],
        }
        self.text = []

    def handle_data(self, data):
        if self.current is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or self.current is None:
            return
        title = self.current["title"].strip()
        if not title:
            title = " ".join("".join(self.text).split())
        if title and len(title) <= 200 and "{" not in title and "}" not in title:
            self.current["title"] = title
            self.identifiers.add(self.current["externalProductId"])
            self.results.append(self.current)
        self.current = None
        self.text = []


def parse_search_results(raw: bytes, store: str, limit: int = 10) -> list[dict]:
    parser = StoreSearchParser(store, limit)
    parser.feed(raw.decode("utf-8", errors="replace"))
    return parser.results


def fetch(url: str, timeout: float = 15.0) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def fetch_product(store: str, product_url: str, timeout: float = 15.0) -> bytes:
    identifier = product_id_from_url(store, product_url)
    if store == "EpicGamesStore":
        url = (
            "https://store-content.ak.epicgames.com/api/ko/content/products/" +
            identifier
        )
        return fetch(url, timeout)
    return fetch(product_url, timeout)


def search(store: str, query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    settings = config(store)
    parameters = dict(settings["searchParameters"])
    parameters["q"] = query.strip()
    url = f"{settings['search']}?{urlencode(parameters)}"
    return parse_search_results(fetch(url, timeout), store, limit)


class ProductDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_json_ld = False
        self.json_ld: list[str] = []
        self.documents: list[dict] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "script" and values.get("type") == "application/ld+json":
            self.in_json_ld = True
            self.json_ld = []
        if tag == "meta":
            key = (
                values.get("itemprop")
                or values.get("property")
                or values.get("name")
            )
            content = values.get("content")
            if key and content:
                self.meta[key] = content

    def handle_data(self, data):
        if self.in_json_ld:
            self.json_ld.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or not self.in_json_ld:
            return
        self.in_json_ld = False
        try:
            document = json.loads("".join(self.json_ld))
        except json.JSONDecodeError:
            return
        if isinstance(document, dict):
            self.documents.append(document)
        elif isinstance(document, list):
            self.documents.extend(item for item in document if isinstance(item, dict))


def nested_documents(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nested_documents(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_documents(child)


def first_product(documents: list[dict]) -> dict:
    product_types = {"Product", "SoftwareApplication", "VideoGame"}
    for document in documents:
        for candidate in nested_documents(document):
            document_type = candidate.get("@type")
            types = {document_type} if isinstance(document_type, str) else set(document_type or [])
            if types & product_types and candidate.get("name"):
                return candidate
    return {}


def named_value(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"].strip()
    return ""


def verified_product(raw: bytes, store: str, product_url: str) -> dict:
    if store == "EpicGamesStore" and raw.lstrip().startswith(b"{"):
        document = json.loads(raw)
        pages = document.get("pages", [])
        detail = next(
            (page for page in pages if page.get("_templateName") == "productDetail"),
            {},
        )
        about = detail.get("data", {}).get("about", {})
        title = str(document.get("productName", "")).strip()
        if not title:
            raise ValueError("Store product has no title")
        developer = str(about.get("developerAttribution", "")).strip()
        return {
            "productId": product_id_from_url(store, product_url),
            "title": title,
            "developer": developer,
            "priceMinor": None,
            "currency": "",
            "allowMissingPrice": True,
            "isGame": True,
            "supportsTargetPlatform": True,
            "platforms": config(store)["platforms"],
            "excludedWords": sorted(
                catalog_matcher.normalized_words(title) &
                catalog_matcher.EXCLUDED_TITLE_WORDS
            ),
        }
    parser = ProductDocumentParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    product = first_product(parser.documents)
    title = named_value(product.get("name")) or parser.meta.get("og:title", "").strip()
    if not title:
        raise ValueError("Store product has no title")
    offer = product.get("offers", {})
    if isinstance(offer, list):
        offer = next((item for item in offer if isinstance(item, dict)), {})
    offer = offer if isinstance(offer, dict) else {}
    price_text = offer.get("price")
    price_minor = None
    if price_text is not None:
        normalized = re.sub(r"[^0-9]", "", str(price_text))
        if normalized:
            price_minor = int(normalized)
    product_id = named_value(product.get("sku"))
    if not product_id:
        product_id = str(product.get("productID", "")).strip()
    if not product_id:
        product_id = product_id_from_url(store, product_url)
    developer = named_value(product.get("brand"))
    if not developer:
        developer = named_value(product.get("author"))
    platforms = config(store)["platforms"]
    if store == "NintendoEShop" and "nintendo switch 2" in title.lower():
        platforms = ["NintendoSwitch2"]
    return {
        "productId": product_id,
        "title": title,
        "developer": developer,
        "priceMinor": price_minor,
        "currency": str(offer.get("priceCurrency", "")),
        "allowMissingPrice": price_minor is None,
        "isGame": True,
        "supportsTargetPlatform": True,
        "platforms": platforms,
        "excludedWords": sorted(
            catalog_matcher.normalized_words(title) &
            catalog_matcher.EXCLUDED_TITLE_WORDS
        ),
    }
