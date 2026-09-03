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
{"@type":"Product","name":"Hades","sku":"70010000033131",
 "brand":{"name":"Supergiant Games"},
 "offers":{"price":"25000","priceCurrency":"KRW"}}
</script>
"""

NINTENDO_SWITCH_2_PRODUCT = NINTENDO_PRODUCT.replace(
    b'"name":"Hades"',
    b'"name":"Hades Nintendo Switch 2 Edition"',
)


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

    def test_distinguishes_nintendo_switch_2_edition(self):
        metadata = storefront_catalog.verified_product(
            NINTENDO_SWITCH_2_PRODUCT,
            "NintendoEShop",
            "https://store.nintendo.co.kr/70010000105995",
        )
        self.assertEqual(metadata["platforms"], ["NintendoSwitch2"])

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
        self.assertEqual(product["productId"], "70010000033131")
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
