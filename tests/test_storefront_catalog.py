import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import add_storefront_catalog_game as catalog_import
import storefront_catalog


EPIC_PRODUCT = b"""
<html><head><meta property="og:title" content="Hades" />
<script type="application/ld+json">
{"@type":"Product","name":"Hades","sku":"hades",
 "brand":{"name":"Supergiant Games"},
 "offers":{"price":"26000","priceCurrency":"KRW"}}
</script></head></html>
"""

NINTENDO_PRODUCT = b"""
<script type="application/ld+json">
{"@type":"Product","name":"Hades","sku":"70010000033128",
 "brand":{"name":"Supergiant Games"},
 "offers":{"price":"25000","priceCurrency":"KRW"}}
</script>
"""

NINTENDO_SWITCH_2_PRODUCT = NINTENDO_PRODUCT.replace(
    b'"name":"Hades"',
    b'"name":"Hades Nintendo Switch 2 Edition"',
)

PLAYSTATION_PRODUCT = b"""
<html><head><meta property="og:image" content="https://image.example/hades.jpg" />
<script type="application/ld+json">
{"@type":"Product","name":"Hades","sku":"UP2125-CUSA27387_00-3466019145463410",
 "brand":{"name":"Supergiant Games"},
 "offers":{"price":"26000","priceCurrency":"KRW"}}
</script></head><body>PS4</body></html>
"""

PLAYSTATION_BUNDLE = """
<html><script type="application/ld+json">
{"@type":"Product","name":"Hazelight 번들","sku":"BUNDLE-1",
 "offers":{"price":"23760","priceCurrency":"KRW"}}
</script><body>PS4 PS5
{"productId":"BUNDLE-1","originalPriceValue":72000,"discountPriceValue":23760}
</body></html>
""".encode()

PLAYSTATION_FRIEND_PASS = PLAYSTATION_PRODUCT.replace(
    b'"name":"Hades"', b'"name":"It Takes Two - Friend\'s Pass"'
).replace(b'"price":"26000"', b'"price":"0"')

MICROSOFT_PRODUCT = b"""
<script type="application/ld+json">
{"@type":"Product","name":"Hades","productID":"9P8DL6W0JBB8",
 "brand":{"name":"Supergiant Games"},
 "offers":{"price":"26000","priceCurrency":"KRW"}}
</script><div>Xbox Series X|S</div>
"""

UBISOFT_PRODUCT = b"""
<html><head><meta property="og:image" content="/images/hades.jpg" />
<script type="application/ld+json">
{"@type":"Product","name":"Hades","brand":{"name":"Ubisoft"},
 "offers":[{"price":"26000","priceCurrency":"KRW"}]}
</script></head></html>
"""

GOG_PRODUCT = json.dumps({
    "id": "1207658787",
    "slug": "heroes_of_might_and_magic_3_complete_edition",
    "productType": "game",
    "title": "Heroes of Might and Magic 3: Complete",
    "developers": ["New World Computing, Inc."],
    "operatingSystems": ["windows", "linux"],
    "coverHorizontal": "https://images.gog-statics.com/hero.png",
    "price": {
        "finalMoney": {"amount": "2.49", "currency": "USD"},
        "baseMoney": {"amount": "9.99", "currency": "USD"},
        "discount": "-75%",
    },
}).encode()

EA_PRODUCT = ("""
<script id="__NEXT_DATA__" type="application/json">%s</script>
""" % json.dumps({
    "props": {"pageProps": {"gameDetails": {
        "name": "EA SPORTS FC 26",
        "developer": "EA Canada",
        "isPurchasableGame": True,
        "packArt": {"ar16X9": "https://image.example/fc26.jpg"},
        "platformDetails": [{
            "slug": "EA-APP",
            "editions": [
                {"slug": "standard", "checkoutId": "Origin.OFR.50.0005763",
                 "isUngatedTrial": False,
                 "price": {"displayTotal": "₩ 77,000",
                           "displayTotalWithDiscount": "₩ 53,900",
                           "discountPercentage": 30, "currency": "KRW"}},
                {"slug": "trial", "checkoutId": "Origin.TRIAL",
                 "isUngatedTrial": True,
                 "price": {"displayTotal": "₩ 0", "currency": "KRW"}},
            ],
        }],
    }}}},
)).encode()

BATTLE_NET_CARD = {
    "id": 1831178,
    "subscriptionId": None,
    "name": "Diablo IV - Standard Edition",
    "productComparisonImageUrl": "//image.example/diablo.jpg",
    "priceInfo": {"price": {
        "currency": "KRW", "fullAmount": "₩62,400", "raw": 15600,
        "discountPercentage": 75, "virtualCurrency": False,
    }},
    "analytics": {"category": "Game"},
}
BATTLE_NET_PRODUCT = (
    '<script>self.__next_f.push(' +
    json.dumps([1, '0:{"products":[' + json.dumps(BATTLE_NET_CARD) + ']}']) +
    ')</script>'
).encode()

ITCH_IO_PRODUCT = b'''<html><head>
<meta content="games/424895" name="itch:path" />
<meta content="https://image.example/a-short-hike.png" property="og:image" />
<script type="application/ld+json">
{"@type":"Product","name":"A Short Hike","offers":{"priceCurrency":"USD",
 "price":"7.99","seller":{"@type":"Organization","name":"adamgryu"}}}
</script></head><body><p>A downloadable game for Windows, macOS, and Linux</p>
<a href="https://itch.io/games/platform-windows">Windows</a>
<a href="https://itch.io/games/platform-osx">macOS</a>
<a href="https://itch.io/games/platform-linux">Linux</a></body></html>'''

HUMBLE_PRODUCT = b'''<html><head>
<script type="application/ld+json">
{"@type":["Product","VideoGame"],"applicationCategory":"VideoGame",
 "name":"Celeste","sku":"celeste_storefront",
 "publisher":"Maddy Makes Games Inc.",
 "image":"https://image.example/celeste.jpg",
 "offers":{"priceCurrency":"USD","price":19.99,
 "availability":"http://schema.org/InStock"}}
</script></head></html>'''

META_QUEST_PRODUCT = b'''<html><head>
<meta property="og:image" content="https://image.example/beat-saber.jpg" />
<script type="application/ld+json">{"@graph":[
{"@type":["SoftwareApplication","Product"],"name":"Beat Saber",
 "sku":"2448060205267927","applicationCategory":"Games",
 "offers":{"price":"30800","priceCurrency":"KRW"}}
]}</script></head></html>'''


class StorefrontCatalogTest(unittest.TestCase):
    def test_parses_epic_and_nintendo_search_results(self):
        epic = storefront_catalog.parse_search_results(
            b'<a href="/ko/p/hades"><span>Hades</span></a>',
            "EpicGamesStore",
        )
        nintendo = storefront_catalog.parse_search_results(
            b'<a href="https://store.nintendo.co.kr/hades.html">Hades</a>',
            "NintendoEShop",
        )
        self.assertEqual(epic[0]["externalProductId"], "hades")
        self.assertEqual(epic[0]["store"], "Epic Games Store")
        self.assertEqual(nintendo[0]["externalProductId"], "hades")
        self.assertEqual(nintendo[0]["platforms"], ["NintendoSwitch"])

    def test_rejects_urls_from_untrusted_hosts(self):
        with self.assertRaisesRegex(ValueError, "must use"):
            storefront_catalog.product_id_from_url(
                "EpicGamesStore",
                "https://example.com/p/hades",
            )

    def test_parses_ubisoft_product_identity_and_krw_price(self):
        url = "https://store.ubisoft.com/kr/hades/660e5a03fbff4e2940488bcd.html"
        self.assertEqual(
            storefront_catalog.product_id_from_url("UbisoftStore", url),
            "660e5a03fbff4e2940488bcd",
        )
        metadata = storefront_catalog.verified_product(
            UBISOFT_PRODUCT, "UbisoftStore", url)
        self.assertEqual(metadata["priceMinor"], 26000)
        self.assertEqual(metadata["currency"], "KRW")
        self.assertEqual(metadata["platforms"], ["Windows"])
        self.assertEqual(
            metadata["imageUrl"],
            "https://store.ubisoft.com/images/hades.jpg",
        )

    def test_ubisoft_search_prioritizes_matching_title(self):
        raw = b'''<a href="/kr/other/111111111111111111111111.html">Other</a>
        <a href="/kr/hades/222222222222222222222222.html">Hades</a>'''
        original_fetch = storefront_catalog.fetch
        storefront_catalog.fetch = lambda url, timeout: raw
        try:
            results = storefront_catalog.search("UbisoftStore", "Hades", 1)
        finally:
            storefront_catalog.fetch = original_fetch
        self.assertEqual(results[0]["title"], "Hades")

    def test_parses_gog_identity_platforms_and_usd_price(self):
        url = "https://www.gog.com/en/game/heroes_of_might_and_magic_3_complete_edition"
        self.assertEqual(
            storefront_catalog.product_id_from_url("GOG", url),
            "heroes_of_might_and_magic_3_complete_edition",
        )
        metadata = storefront_catalog.verified_product(GOG_PRODUCT, "GOG", url)
        self.assertEqual(metadata["productId"], "1207658787")
        self.assertEqual(metadata["priceMinor"], 249)
        self.assertEqual(metadata["regularPriceMinor"], 999)
        self.assertEqual(metadata["discountPercent"], 75)
        self.assertEqual(metadata["currency"], "USD")
        self.assertEqual(metadata["platforms"], ["Windows", "Linux"])

    def test_gog_search_only_returns_base_games(self):
        raw = json.dumps({"products": [
            {"id": "1", "slug": "game", "productType": "game",
             "title": "Game", "operatingSystems": ["windows"]},
            {"id": "2", "slug": "game_dlc", "productType": "dlc",
             "title": "Game DLC", "operatingSystems": ["windows"]},
        ]}).encode()
        original_fetch = storefront_catalog.fetch
        storefront_catalog.fetch = lambda url, timeout: raw
        try:
            results = storefront_catalog.search("GOG", "Game", 10)
        finally:
            storefront_catalog.fetch = original_fetch
        self.assertEqual([result["externalProductId"] for result in results], ["1"])
        self.assertEqual(
            results[0]["productUrl"],
            "https://www.gog.com/en/game/game?productId=1",
        )

    def test_parses_meta_quest_product_identity_and_krw_price(self):
        url = "https://www.meta.com/experiences/beat-saber/2448060205267927/"
        self.assertEqual(
            storefront_catalog.product_id_from_url("MetaQuestStore", url),
            "2448060205267927",
        )
        metadata = storefront_catalog.verified_product(
            META_QUEST_PRODUCT, "MetaQuestStore", url)
        self.assertEqual(metadata["productId"], "2448060205267927")
        self.assertEqual(metadata["title"], "Beat Saber")
        self.assertEqual(metadata["priceMinor"], 30800)
        self.assertEqual(metadata["currency"], "KRW")
        self.assertEqual(metadata["platforms"], ["MetaQuest"])
        self.assertEqual(metadata["imageUrl"], "https://image.example/beat-saber.jpg")

    def test_parses_ea_app_standard_edition_and_ignores_trial(self):
        url = "https://www.ea.com/ko/games/ea-sports-fc/fc-26/buy"
        self.assertEqual(
            storefront_catalog.product_id_from_url("EAApp", url), "fc-26")
        metadata = storefront_catalog.verified_product(EA_PRODUCT, "EAApp", url)
        self.assertEqual(metadata["productId"], "Origin.OFR.50.0005763")
        self.assertEqual(metadata["title"], "EA SPORTS FC 26")
        self.assertEqual(metadata["priceMinor"], 53900)
        self.assertEqual(metadata["regularPriceMinor"], 77000)
        self.assertEqual(metadata["discountPercent"], 30)
        self.assertEqual(metadata["currency"], "KRW")
        self.assertEqual(metadata["platforms"], ["Windows"])

    def test_parses_battle_net_base_game_price(self):
        url = "https://kr.shop.battle.net/ko-kr/product/diablo-iv"
        self.assertEqual(
            storefront_catalog.product_id_from_url("BattleNet", url),
            "diablo-iv",
        )
        metadata = storefront_catalog.verified_product(
            BATTLE_NET_PRODUCT, "BattleNet", url)
        self.assertEqual(metadata["productId"], "1831178")
        self.assertEqual(metadata["title"], "Diablo IV")
        self.assertEqual(metadata["priceMinor"], 15600)
        self.assertEqual(metadata["regularPriceMinor"], 62400)
        self.assertEqual(metadata["discountPercent"], 75)
        self.assertEqual(metadata["currency"], "KRW")
        self.assertEqual(metadata["platforms"], ["Windows"])

    def test_parses_paid_itch_io_desktop_game(self):
        url = "https://adamgryu.itch.io/a-short-hike"
        self.assertEqual(
            storefront_catalog.product_id_from_url("ItchIo", url),
            "adamgryu/a-short-hike",
        )
        metadata = storefront_catalog.verified_product(
            ITCH_IO_PRODUCT, "ItchIo", url)
        self.assertEqual(metadata["productId"], "424895")
        self.assertEqual(metadata["title"], "A Short Hike")
        self.assertEqual(metadata["developer"], "adamgryu")
        self.assertEqual(metadata["priceMinor"], 799)
        self.assertEqual(metadata["currency"], "USD")
        self.assertEqual(metadata["platforms"], ["Windows", "macOS", "Linux"])

    def test_rejects_itch_io_non_game_project(self):
        raw = ITCH_IO_PRODUCT.replace(
            b"A downloadable game", b"A downloadable asset pack")
        with self.assertRaisesRegex(ValueError, "not identified as a video game"):
            storefront_catalog.verified_product(
                raw, "ItchIo", "https://artist.itch.io/assets")

    def test_parses_humble_store_video_game(self):
        url = "https://www.humblebundle.com/store/celeste"
        self.assertEqual(
            storefront_catalog.product_id_from_url("HumbleStore", url),
            "celeste",
        )
        metadata = storefront_catalog.verified_product(
            HUMBLE_PRODUCT, "HumbleStore", url)
        self.assertEqual(metadata["productId"], "celeste_storefront")
        self.assertEqual(metadata["title"], "Celeste")
        self.assertEqual(metadata["developer"], "Maddy Makes Games Inc.")
        self.assertEqual(metadata["priceMinor"], 1999)
        self.assertEqual(metadata["currency"], "USD")
        self.assertEqual(metadata["platforms"], ["Windows"])
        game = {
            "title": "Celeste",
            "aliases": [],
            "developers": ["Maddy Makes Games Inc."],
            "publishers": [],
        }
        decision = catalog_import.catalog_matcher.evaluate(game, metadata)
        self.assertEqual(decision["status"], "ApprovedCandidate")
        self.assertIn(
            "Store identifies this game as a paid USD purchase",
            decision["reasons"],
        )

    def test_rejects_humble_store_non_game_product(self):
        raw = HUMBLE_PRODUCT.replace(
            b'["Product","VideoGame"]', b'"Product"').replace(
            b'"VideoGame"', b'"SoftwareApplication"')
        with self.assertRaisesRegex(ValueError, "not identified as a video game"):
            storefront_catalog.verified_product(
                raw, "HumbleStore",
                "https://www.humblebundle.com/store/not-a-game")

    def test_distinguishes_playstation_console_generation(self):
        metadata = storefront_catalog.verified_product(
            PLAYSTATION_PRODUCT,
            "PlayStationStore",
            "https://store.playstation.com/ko-kr/product/UP2125-CUSA27387_00-3466019145463410",
        )
        self.assertEqual(metadata["platforms"], ["PlayStation4"])
        self.assertEqual(
            metadata["imageUrl"],
            "https://image.example/hades.jpg",
        )

    def test_parses_playstation_bundle_purchase_offer(self):
        metadata = storefront_catalog.verified_product(
            PLAYSTATION_BUNDLE,
            "PlayStationStore",
            "https://store.playstation.com/ko-kr/product/BUNDLE-1",
        )
        self.assertEqual(metadata["offerType"], "Bundle")
        self.assertEqual(metadata["offerName"], "Hazelight 번들")
        self.assertEqual(metadata["priceMinor"], 23760)
        self.assertEqual(metadata["regularPriceMinor"], 72000)
        self.assertEqual(metadata["discountPercent"], 67)

    def test_bundle_requires_review_and_can_attach_to_included_game(self):
        catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "it-takes-two",
                "title": "It Takes Two",
                "developers": ["Hazelight Studios"],
                "platforms": ["PlayStation5"],
                "products": [],
            }],
        }
        metadata = storefront_catalog.verified_product(
            PLAYSTATION_BUNDLE,
            "PlayStationStore",
            "https://store.playstation.com/ko-kr/product/BUNDLE-1",
        )
        unchanged, preview = catalog_import.updated_catalog(
            catalog,
            "PlayStationStore",
            "https://store.playstation.com/ko-kr/product/BUNDLE-1",
            "it-takes-two",
            metadata,
        )
        self.assertEqual(preview["matchDecision"]["status"], "NeedsReview")
        self.assertEqual(unchanged["games"][0]["products"], [])

        updated, _ = catalog_import.updated_catalog(
            catalog,
            "PlayStationStore",
            "https://store.playstation.com/ko-kr/product/BUNDLE-1",
            "it-takes-two",
            metadata,
            acknowledge_review=True,
        )
        product = updated["games"][0]["products"][0]
        self.assertEqual(product["offerType"], "Bundle")
        self.assertEqual(product["offerName"], "Hazelight 번들")

    def test_rejects_playstation_friend_pass(self):
        with self.assertRaisesRegex(ValueError, "friend-pass"):
            storefront_catalog.verified_product(
                PLAYSTATION_FRIEND_PASS,
                "PlayStationStore",
                "https://store.playstation.com/ko-kr/product/FRIEND-PASS",
            )

    def test_distinguishes_xbox_console_generation(self):
        metadata = storefront_catalog.verified_product(
            MICROSOFT_PRODUCT,
            "MicrosoftStore",
            "https://www.xbox.com/ko-KR/games/store/hades/9P8DL6W0JBB8",
        )
        self.assertEqual(metadata["platforms"], ["XboxSeries"])

    def test_rejects_console_product_without_generation_metadata(self):
        raw = PLAYSTATION_PRODUCT.replace(b"PS4", b"console")
        with self.assertRaisesRegex(ValueError, "console generation"):
            storefront_catalog.verified_product(
                raw,
                "PlayStationStore",
                "https://store.playstation.com/ko-kr/product/UP2125-CUSA27387_00-3466019145463410",
            )

    def test_rejects_global_nintendo_product_for_kr_catalog(self):
        catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "hades",
                "title": "Hades",
                "developers": [],
                "platforms": ["NintendoSwitch"],
                "products": [],
            }],
        }
        with self.assertRaisesRegex(ValueError, "Nintendo KR catalog"):
            catalog_import.updated_catalog(
                catalog,
                "NintendoEShop",
                "https://www.nintendo.com/us/store/products/hades-switch/",
                "hades",
                {"productId": "70010000033131"},
            )

    def test_distinguishes_nintendo_switch_2_edition(self):
        metadata = storefront_catalog.verified_product(
            NINTENDO_SWITCH_2_PRODUCT,
            "NintendoEShop",
            "https://store.nintendo.co.kr/70010000105995",
        )
        self.assertEqual(metadata["platforms"], ["NintendoSwitch2"])

    def test_reads_switch_2_target_console_without_title_suffix(self):
        document = """
        <div class="product-attribute label_platform_attr">
          <div class="product-attribute-val">Nintendo Switch 2</div>
        </div>
        """
        self.assertEqual(
            storefront_catalog.nintendo_platforms(document),
            ["NintendoSwitch2"],
        )

    def test_reads_nintendo_magento_price(self):
        document = (
            '"price_info":{"final_price":89800,"max_regular_price":99800}'
            ',"currency_code":"KRW"'
        )
        self.assertEqual(
            storefront_catalog.nintendo_magento_price(document),
            (89800, 99800, "KRW"),
        )

    def test_reads_nintendo_korean_publisher_for_identity_matching(self):
        raw = (ROOT / "tests/fixtures/nintendo_hades_product.html").read_bytes()
        metadata = storefront_catalog.verified_product(
            raw,
            "NintendoEShop",
            "https://store.nintendo.co.kr/70010000033128",
        )
        self.assertEqual(metadata["developer"], "Supergiant Games")

    def test_missing_price_requires_identity_review_instead_of_rejection(self):
        metadata = storefront_catalog.verified_product(
            json.dumps({
                "productName": "Hades",
                "_slug": "hades",
                "pages": [{
                    "_templateName": "productDetail",
                    "data": {"about": {"developerAttribution": "Supergiant Games"}},
                }],
            }).encode(),
            "EpicGamesStore",
            "https://store.epicgames.com/ko/p/hades",
        )
        game = {"title": "Hades", "developers": ["Supergiant Games"]}
        decision = catalog_import.catalog_matcher.evaluate(game, metadata)
        self.assertEqual(decision["status"], "ApprovedCandidate")
        self.assertIn(
            "Price is unavailable during catalog review",
            decision["reasons"],
        )

    def test_attaches_verified_storefront_products(self):
        catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "hades",
                "title": "Hades",
                "developers": ["Supergiant Games"],
                "platforms": ["Windows"],
                "products": [],
            }],
        }
        metadata = storefront_catalog.verified_product(
            NINTENDO_PRODUCT,
            "NintendoEShop",
            "https://store.nintendo.co.kr/hades.html",
        )
        updated, preview = catalog_import.updated_catalog(
            catalog,
            "NintendoEShop",
            "https://store.nintendo.co.kr/hades.html",
            "hades",
            metadata,
        )
        product = updated["games"][0]["products"][0]
        self.assertEqual(product["productId"], "70010000033128")
        self.assertEqual(product["store"], "NintendoEShop")
        self.assertEqual(preview["matchDecision"]["status"], "ApprovedCandidate")

    def test_apply_is_audited_and_preserves_existing_game(self):
        catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "hades",
                "title": "Hades",
                "developers": ["Supergiant Games"],
                "platforms": ["Windows"],
                "products": [],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.json"
            database_path = Path(directory) / "catalog.db"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            result = catalog_import.import_game(
                catalog_path,
                EPIC_PRODUCT,
                "EpicGamesStore",
                "https://store.epicgames.com/ko/p/hades",
                "hades",
                True,
                database_path=database_path,
            )
            self.assertEqual(result["matchedProduct"]["productId"], "hades")
            saved = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["games"][0]["products"][0]["store"], "EpicGamesStore")
            self.assertTrue(catalog_path.with_suffix(".json.bak").exists())


if __name__ == "__main__":
    unittest.main()
