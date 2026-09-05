import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import catalog_matcher


SPEC = importlib.util.spec_from_file_location(
    "microsoft_catalog_search",
    ROOT / "tools" / "search_microsoft_catalog.py",
)
search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(search)


def summary(product_id: str, title: str, kind: str, platforms: list[str]) -> dict:
    return {
        "productId": product_id,
        "title": title,
        "productKind": kind,
        "availableOn": platforms,
        "developerName": "ConcernedApe",
        "images": {
            "poster": {"url": f"https://images.example/{product_id}.jpg"},
        },
    }


def product_document(
    product_type: str = "Game",
    actions: list[str] | None = None,
    price: float = 16000.0,
    currency: str = "KRW",
) -> bytes:
    return json.dumps({
        "Products": [{
            "ProductId": "GAME-1",
            "ProductType": product_type,
            "LocalizedProperties": [{
                "ProductTitle": "Stardew Valley",
                "DeveloperName": "ConcernedApe",
                "Images": [{
                    "ImagePurpose": "Poster",
                    "Uri": "//images.example/stardew.jpg",
                }],
            }],
            "Properties": {
                "XboxConsoleGenCompatible": ["ConsoleGen8", "ConsoleGen9"],
            },
            "DisplaySkuAvailabilities": [{
                "Availabilities": [{
                    "Actions": actions or ["Purchase"],
                    "OrderManagementData": {
                        "Price": {
                            "CurrencyCode": currency,
                            "ListPrice": price,
                        },
                    },
                }],
            }],
        }],
    }).encode("utf-8")


class MicrosoftCatalogSearchTest(unittest.TestCase):
    def test_search_keeps_xbox_games_and_excludes_addons_and_pc_only(self):
        response = {
            "productSummaries": [
                summary("GAME", "Stardew Valley", "Game", ["XboxOne", "XboxSeriesX"]),
                summary("DLC", "Stardew Valley DLC", "Durable", ["XboxOne"]),
                summary("PC", "Stardew Valley PC", "Game", ["PC"]),
            ],
        }
        with patch.object(search, "fetch_json", return_value=response):
            results = search.search("Stardew Valley", 10, 1.0)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["externalProductId"], "GAME")
        self.assertEqual(results[0]["platforms"], ["XboxOne", "XboxSeries"])

    def test_verified_product_reads_purchase_price_and_console_generations(self):
        metadata = search.verified_product(product_document(), "GAME-1")

        self.assertEqual(metadata["priceMinor"], 16000)
        self.assertEqual(metadata["currency"], "KRW")
        self.assertEqual(metadata["platforms"], ["XboxOne", "XboxSeries"])
        self.assertTrue(metadata["isGame"])
        self.assertTrue(metadata["supportsTargetPlatform"])

    def test_subscription_only_availability_is_not_treated_as_purchase(self):
        raw = product_document(actions=["License"], price=0.0)

        metadata = search.verified_product(raw, "GAME-1")

        self.assertIsNone(metadata["priceMinor"])
        self.assertEqual(metadata["currency"], "")
        self.assertFalse(metadata["supportsTargetPlatform"])

    def test_wrong_currency_is_not_accepted_as_korean_purchase_price(self):
        metadata = search.verified_product(
            product_document(currency="USD"),
            "GAME-1",
        )

        self.assertIsNone(metadata["priceMinor"])
        self.assertEqual(metadata["currency"], "")

    def test_deluxe_game_is_marked_as_non_standard_offer(self):
        raw = product_document().replace(
            b"Stardew Valley",
            b"Stardew Valley Deluxe Edition",
        )

        metadata = search.verified_product(raw, "GAME-1")
        game = {
            "title": "Stardew Valley",
            "aliases": [],
            "developers": ["ConcernedApe"],
            "publishers": [],
        }
        decision = catalog_matcher.evaluate(game, metadata)

        self.assertIn("deluxe", metadata["excludedWords"])
        self.assertEqual(decision["status"], "Rejected")


if __name__ == "__main__":
    unittest.main()
