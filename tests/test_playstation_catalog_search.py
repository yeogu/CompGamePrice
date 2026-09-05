import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "playstation_catalog_search",
    ROOT / "tools" / "search_playstation_catalog.py",
)
search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(search)


def product(product_id: str, title: str, classification: str, platforms: list[str]) -> dict:
    return {
        "id": product_id,
        "name": title,
        "storeDisplayClassification": classification,
        "platforms": platforms,
        "media": [{
            "type": "IMAGE",
            "role": "MASTER",
            "url": f"https://images.example/{product_id}.jpg",
        }],
    }


class PlayStationCatalogSearchTest(unittest.TestCase):
    def test_catalog_keeps_full_games_and_merges_console_generations(self):
        pages = {
            search.CATEGORIES["PlayStation4"]: [
                product("GAME-1", "Stardew Valley", "FULL_GAME", ["PS4"]),
                product("DLC-1", "Stardew Valley DLC", "ADD_ON", ["PS4"]),
            ],
            search.CATEGORIES["PlayStation5"]: [
                product("GAME-1", "Stardew Valley", "FULL_GAME", ["PS5"]),
            ],
        }

        def fetch_page(category_id, offset, timeout):
            del offset
            del timeout
            return {
                "products": pages[category_id],
                "pageInfo": {"isLast": True, "size": 1000, "totalCount": 2},
            }

        catalog = search.load_catalog(1.0, fetch_page)

        self.assertEqual(len(catalog), 1)
        self.assertEqual(
            catalog[0]["platforms"],
            ["PlayStation4", "PlayStation5"],
        )

    def test_search_prefers_matching_title(self):
        finder = search.PlayStationCatalogSearch(loader=lambda timeout: [
            search.candidate_from_product(
                product("OTHER", "Farming Simulator", "FULL_GAME", ["PS5"]),
            ),
            search.candidate_from_product(
                product("MATCH", "Stardew Valley", "FULL_GAME", ["PS5"]),
            ),
        ])

        results = finder.search("Stardew Valley", 5, 1.0)

        self.assertEqual(results[0]["externalProductId"], "MATCH")

    def test_product_metadata_uses_publisher_price_and_platform(self):
        raw = json.dumps({
            "data": {
                "productRetrieve": {
                    "id": "GAME-1",
                    "name": "Stardew Valley",
                    "publisherName": "ConcernedApe",
                    "topCategory": "GAME",
                    "storeDisplayClassification": "FULL_GAME",
                    "platforms": ["PS4", "PS5"],
                    "price": {
                        "discountedPrice": "6,600원",
                        "isFree": False,
                        "isTiedToSubscription": False,
                    },
                    "media": [],
                },
            },
        }).encode("utf-8")

        metadata = search.verified_product(raw, "GAME-1")

        self.assertEqual(metadata["developer"], "ConcernedApe")
        self.assertEqual(metadata["priceMinor"], 6600)
        self.assertEqual(metadata["currency"], "KRW")
        self.assertTrue(metadata["isGame"])
        self.assertEqual(
            metadata["platforms"],
            ["PlayStation4", "PlayStation5"],
        )

    def test_subscription_only_offer_is_not_a_supported_purchase(self):
        raw = json.dumps({
            "data": {
                "productRetrieve": {
                    "name": "Stardew Valley",
                    "publisherName": "ConcernedApe",
                    "topCategory": "GAME",
                    "storeDisplayClassification": "FULL_GAME",
                    "platforms": ["PS5"],
                    "price": {
                        "discountedPrice": "0원",
                        "isFree": False,
                        "isTiedToSubscription": True,
                    },
                    "media": [],
                },
            },
        }).encode("utf-8")

        metadata = search.verified_product(raw, "GAME-1")

        self.assertFalse(metadata["supportsTargetPlatform"])


if __name__ == "__main__":
    unittest.main()
