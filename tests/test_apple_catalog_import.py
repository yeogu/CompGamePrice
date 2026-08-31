import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "apple_import",
    ROOT / "tools" / "add_apple_catalog_game.py",
)
catalog_import = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(catalog_import)


class AppleCatalogImportTest(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / "tests/fixtures/apple_lookup_1406710800.json").read_bytes()
        self.catalog = {
            "schemaVersion": 4,
            "games": [{"id": "stardew-valley", "title": "스타듀 밸리", "aliases": ["Stardew Valley"], "developers": ["ConcernedApe"], "platforms": ["Windows"], "products": []}],
        }

    def test_approves_alias_developer_and_iphone_ipad_offer(self):
        metadata = catalog_import.apple_product(self.raw, "1406710800")
        updated, game = catalog_import.updated_catalog(
            self.catalog,
            "stardew-valley",
            "1406710800",
            metadata,
        )
        self.assertEqual(game["matchDecision"]["status"], "ApprovedCandidate")
        self.assertTrue(game["matchDecision"]["developerMatched"])
        self.assertEqual(game["matchedProduct"]["platforms"], ["iOS", "iPadOS"])
        self.assertIn("iOS", updated["games"][0]["platforms"])

    def test_supports_iphone_only_game(self):
        document = json.loads(self.raw)
        document["results"][0]["supportedDevices"] = ["iPhone12-iPhone12"]
        metadata = catalog_import.apple_product(json.dumps(document).encode(), "1406710800")
        self.assertEqual(metadata["platforms"], ["iOS"])

    def test_rejects_free_wrong_currency_and_guide(self):
        metadata = catalog_import.apple_product(self.raw, "1406710800")
        for change in [
            {"priceMinor": 0},
            {"currency": "USD"},
            {"title": "Stardew Valley Guide", "excludedWords": ["guide"]},
        ]:
            decision = catalog_import.catalog_matcher.evaluate(
                self.catalog["games"][0],
                {**metadata, **change},
            )
            self.assertEqual(decision["status"], "Rejected")

    def test_rejects_developer_mismatch_and_cross_game_track_id(self):
        metadata = catalog_import.apple_product(self.raw, "1406710800")
        metadata["developer"] = "Different Studio"
        decision = catalog_import.catalog_matcher.evaluate(self.catalog["games"][0], metadata)
        self.assertEqual(decision["status"], "Rejected")
        self.catalog["games"][0]["products"] = [{"store": "AppleAppStore", "productId": "1406710800"}]
        self.catalog["games"].append({
            "id": "different-game",
            "title": "Different Game",
            "platforms": ["iOS"],
            "products": [],
        })
        with self.assertRaisesRegex(ValueError, "already belongs"):
            catalog_import.updated_catalog(
                self.catalog,
                "different-game",
                "1406710800",
                catalog_import.apple_product(self.raw, "1406710800"),
            )

    def test_approves_official_publisher_identity(self):
        self.catalog["games"][0]["publishers"] = ["505 Games"]
        metadata = catalog_import.apple_product(self.raw, "1406710800")
        metadata["developer"] = "505 Games (US), Inc."
        decision = catalog_import.catalog_matcher.evaluate(
            self.catalog["games"][0],
            metadata,
        )
        self.assertEqual(decision["status"], "ApprovedCandidate")
        self.assertTrue(decision["publisherMatched"])

    def test_needs_review_requires_acknowledgement(self):
        self.catalog["games"][0]["developers"] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit acknowledgement"):
                catalog_import.import_game(
                    path,
                    self.raw,
                    "1406710800",
                    "stardew-valley",
                    True,
                )


if __name__ == "__main__":
    unittest.main()
