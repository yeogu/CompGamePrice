"""Shared HTML discovery and product parsing for console/PC storefronts."""

from __future__ import annotations

from html.parser import HTMLParser
from html import unescape
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
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
    "PlayStationStore": {
        "display": "PlayStation Store",
        "hosts": ["store.playstation.com"],
        "search": "https://store.playstation.com/ko-kr/search/",
        "searchParameters": {},
        "productPath": "/product/",
        "platforms": ["PlayStation4", "PlayStation5"],
    },
    "MicrosoftStore": {
        "display": "Microsoft Store",
        "hosts": ["www.xbox.com", "apps.microsoft.com"],
        "search": "https://www.xbox.com/ko-KR/search/results",
        "searchParameters": {},
        "productPath": "/games/store/",
        "platforms": ["XboxOne", "XboxSeries"],
    },
    "UbisoftStore": {
        "display": "Ubisoft Store",
        "hosts": ["store.ubisoft.com"],
        "search": "https://store.ubisoft.com/kr/games",
        "searchParameters": {},
        "productPath": "/kr/",
        "platforms": ["Windows"],
    },
    "GOG": {
        "display": "GOG",
        "hosts": ["www.gog.com", "gog.com"],
        "search": "https://catalog.gog.com/v1/catalog",
        "searchParameters": {
            "productType": "in:game",
            "countryCode": "KR",
            "locale": "en-US",
            "currencyCode": "USD",
            "page": "1",
        },
        "productPath": "/en/game/",
        "platforms": ["Windows", "macOS", "Linux"],
    },
    "MetaQuestStore": {
        "display": "Meta Quest Store",
        "hosts": ["www.meta.com", "meta.com"],
        "search": "https://www.meta.com/experiences/search/",
        "searchParameters": {},
        "productPath": "/experiences/",
        "platforms": ["MetaQuest"],
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
    if store == "PlayStationStore":
        try:
            marker = parts.index("product")
            return parts[marker + 1]
        except (ValueError, IndexError) as error:
            raise ValueError("invalid PlayStation Store product URL") from error
    if store == "MicrosoftStore":
        if len(parts) < 2:
            raise ValueError("invalid Microsoft Store product URL")
        return parts[-1]
    if store == "UbisoftStore":
        if len(parts) < 3 or parts[0] != "kr":
            raise ValueError("invalid Ubisoft Store product URL")
        identifier = parts[-1].removesuffix(".html")
        if not re.fullmatch(r"[0-9a-f]{24}", identifier):
            raise ValueError("invalid Ubisoft Store product URL")
        return identifier
    if store == "GOG":
        try:
            marker = parts.index("game")
            identifier = parts[marker + 1]
        except (ValueError, IndexError) as error:
            raise ValueError("invalid GOG product URL") from error
        if not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise ValueError("invalid GOG product URL")
        return identifier
    if store == "MetaQuestStore":
        if "experiences" not in parts or not parts[-1].isdigit():
            raise ValueError("invalid Meta Quest Store product URL")
        return parts[-1]
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
        if self.store == "UbisoftStore" and title.startswith("상품으로 이동:"):
            title = title.split(":", 1)[1].strip()
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
    if store == "GOG":
        product_ids = parse_qs(urlparse(product_url).query).get("productId", [])
        if product_ids and product_ids[0].isdigit():
            return fetch_gog_product(product_ids[0], timeout)
        parameters = dict(config(store)["searchParameters"])
        parameters.update({"query": identifier, "limit": "20"})
        document = json.loads(fetch(
            f"{config(store)['search']}?{urlencode(parameters)}", timeout))
        product = next(
            (item for item in document.get("products", [])
             if item.get("slug") == identifier),
            None,
        )
        if product is None:
            raise ValueError("GOG product was not found")
        return json.dumps(product).encode("utf-8")
    return fetch(product_url, timeout)


def fetch_gog_product(product_id: str, timeout: float = 15.0) -> bytes:
    if not str(product_id).isdigit():
        raise ValueError("invalid GOG product ID")
    detail = json.loads(fetch(
        f"https://api.gog.com/products/{product_id}", timeout))
    price_document = json.loads(fetch(
        f"https://api.gog.com/products/{product_id}/prices?countryCode=KR",
        timeout,
    ))
    prices = price_document.get("_embedded", {}).get("prices", [])
    price = prices[0] if prices else {}
    currency = str(price.get("currency", {}).get("code", ""))

    def price_amount(value: str) -> str | None:
        text = str(value or "").strip()
        minor = text.split(" ", 1)[0]
        if not minor.isdigit() or not currency:
            return None
        exponent = 0 if currency in {"KRW", "JPY"} else 2
        return str(Decimal(minor) / (10 ** exponent))

    compatibility = detail.get("content_system_compatibility", {})
    platforms = []
    if compatibility.get("windows"):
        platforms.append("windows")
    if compatibility.get("osx"):
        platforms.append("osx")
    if compatibility.get("linux"):
        platforms.append("linux")
    images = detail.get("images", {})
    image = str(images.get("background") or images.get("logo2x") or "")
    if image.startswith("//"):
        image = "https:" + image
    base_amount = price_amount(price.get("basePrice", ""))
    final_amount = price_amount(price.get("finalPrice", ""))
    return json.dumps({
        "id": str(detail.get("id", product_id)),
        "slug": detail.get("slug", ""),
        "productType": "game" if detail.get("game_type") == "game" else detail.get("game_type", "game"),
        "title": detail.get("title", ""),
        "developers": [],
        "operatingSystems": platforms,
        "coverHorizontal": image,
        "price": {
            "finalMoney": {"amount": final_amount, "currency": currency},
            "baseMoney": {"amount": base_amount, "currency": currency},
            "discount": None,
        },
    }).encode("utf-8")


def search(store: str, query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    if not query.strip():
        raise ValueError("search query is required")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    settings = config(store)
    parameters = dict(settings["searchParameters"])
    parameters["q"] = query.strip()
    if store == "GOG":
        parameters.pop("q")
        parameters.update({"query": query.strip(), "limit": str(limit)})
        document = json.loads(fetch(
            f"{settings['search']}?{urlencode(parameters)}", timeout))
        results = []
        for product in document.get("products", []):
            if product.get("productType") != "game":
                continue
            slug = str(product.get("slug", "")).strip()
            title = str(product.get("title", "")).strip()
            if not slug or not title:
                continue
            price = product.get("price") or {}
            final_money = price.get("finalMoney") or {}
            currency = str(final_money.get("currency", "")).upper()
            results.append({
                "store": settings["display"],
                "externalProductId": str(product.get("id", slug)),
                "title": title,
                "productUrl": (
                    f"https://www.gog.com/en/game/{slug}?"
                    f"{urlencode({'productId': str(product.get('id', ''))})}"
                ),
                "platforms": gog_platforms(product),
                "imageUrl": str(product.get("coverHorizontal", "")),
                "developer": next(iter(product.get("developers") or []), ""),
                "priceMinor": decimal_minor(final_money.get("amount"), currency)
                if currency else None,
                "currency": currency,
            })
        return results[:limit]
    url = f"{settings['search']}?{urlencode(parameters)}"
    parse_limit = 200 if store == "UbisoftStore" else limit
    results = parse_search_results(fetch(url, timeout), store, parse_limit)
    if store == "UbisoftStore":
        query_words = catalog_matcher.normalized_words(query)
        normalized_query = " ".join(str(query).casefold().split())
        results.sort(
            key=lambda candidate: (
                " ".join(candidate["title"].casefold().split()) != normalized_query,
                len(catalog_matcher.normalized_words(candidate["title"]) ^ query_words),
                -len(query_words & catalog_matcher.normalized_words(candidate["title"])),
                candidate["title"].casefold(),
            )
        )
    return results[:limit]


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


def gog_platforms(product: dict) -> list[str]:
    names = {str(value).casefold() for value in product.get("operatingSystems", [])}
    platforms = []
    if "windows" in names:
        platforms.append("Windows")
    if "osx" in names or "mac" in names or "macos" in names:
        platforms.append("macOS")
    if "linux" in names:
        platforms.append("Linux")
    return platforms or ["Windows"]


def decimal_minor(value, currency: str) -> int | None:
    if value is None:
        return None
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Store product has an invalid price") from error
    exponent = 0 if currency in {"KRW", "JPY"} else 2
    return int(decimal * (10 ** exponent))


def nintendo_publisher(document: str) -> str:
    publisher = re.search(
        r'class="product-attribute\s+publisher[^\"]*".*?'
        r'class="attribute-item-val"[^>]*>(.*?)</div>',
        document,
        re.IGNORECASE | re.DOTALL,
    )
    if not publisher:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", publisher.group(1))
    return " ".join(unescape(without_tags).split())


def verified_product(raw: bytes, store: str, product_url: str) -> dict:
    if store == "GOG" and raw.lstrip().startswith(b"{"):
        product = json.loads(raw)
        if product.get("productType") != "game":
            raise ValueError("GOG product is not a base game")
        title = str(product.get("title", "")).strip()
        if not title:
            raise ValueError("Store product has no title")
        price = product.get("price") or {}
        final_money = price.get("finalMoney") or {}
        base_money = price.get("baseMoney") or {}
        currency = str(final_money.get("currency", "")).upper()
        if currency not in {"KRW", "USD", "EUR", "GBP", "JPY"}:
            raise ValueError("GOG product uses an unsupported currency")
        current_minor = decimal_minor(final_money.get("amount"), currency)
        regular_minor = decimal_minor(base_money.get("amount"), currency)
        discount_text = str(price.get("discount") or "").strip("-%")
        discount_percent = int(discount_text) if discount_text.isdigit() else 0
        if not discount_percent and current_minor is not None and regular_minor:
            discount_percent = round(
                (regular_minor - current_minor) * 100 / regular_minor)
        return {
            "productId": str(product.get("id", "")).strip(),
            "title": title,
            "developer": next(iter(product.get("developers") or []), ""),
            "priceMinor": current_minor,
            "regularPriceMinor": regular_minor,
            "currency": currency,
            "discountPercent": max(0, discount_percent),
            "allowMissingPrice": final_money.get("amount") is None,
            "isGame": True,
            "supportsTargetPlatform": True,
            "platforms": gog_platforms(product),
            "imageUrl": str(product.get("coverHorizontal", "")),
            "excludedWords": sorted(
                catalog_matcher.normalized_words(title) &
                catalog_matcher.EXCLUDED_TITLE_WORDS
            ),
        }
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
    html_document = raw.decode("utf-8", errors="replace")
    parser = ProductDocumentParser()
    parser.feed(html_document)
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
    if not developer and store == "NintendoEShop":
        developer = nintendo_publisher(html_document)
    platforms = config(store)["platforms"]
    if store == "NintendoEShop" and "nintendo switch 2" in title.lower():
        platforms = ["NintendoSwitch2"]
    normalized_document = html_document.casefold()
    if store == "PlayStationStore":
        platforms = []
        if "ps4" in normalized_document:
            platforms.append("PlayStation4")
        if "ps5" in normalized_document:
            platforms.append("PlayStation5")
    if store == "MicrosoftStore":
        platforms = []
        if "xbox one" in normalized_document:
            platforms.append("XboxOne")
        if "series x|s" in normalized_document or "series x/s" in normalized_document:
            platforms.append("XboxSeries")
    if not platforms and store in {"PlayStationStore", "MicrosoftStore"}:
        raise ValueError(
            f"{config(store)['display']} product page does not identify "
            "a supported console generation",
        )
    if not platforms:
        platforms = config(store)["platforms"]
    image_url = named_value(product.get("image"))
    if not image_url:
        image_url = parser.meta.get("og:image", "").strip()
    image_url = urljoin(product_url, image_url)
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
        "imageUrl": image_url,
        "excludedWords": sorted(
            catalog_matcher.normalized_words(title) &
            catalog_matcher.EXCLUDED_TITLE_WORDS
        ),
    }
