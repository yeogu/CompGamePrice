import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "google_play_import",
    ROOT / "tools" / "add_google_play_catalog_game.py",
)
catalog_import = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(catalog_import)


class GooglePlayCatalogImportTest(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / "tests/fixtures/google_play_stardew.html").read_bytes()
        self.catalog = {
            "schemaVersion": 4,
            "games": [{"id": "stardew-valley", "title": "스타듀 밸리", "aliases": ["Stardew Valley"], "developers": ["ConcernedApe"], "platforms": ["Windows"], "products": []}],
        }

    def test_attaches_verified_product_to_existing_game(self):
        metadata = catalog_import.verified_product(self.raw, "com.chucklefish.stardewvalley")
        updated, game = catalog_import.updated_catalog(
            self.catalog,
            "stardew-valley",
            "com.chucklefish.stardewvalley",
            metadata,
        )
        self.assertIn("Android", game["platforms"])
        self.assertEqual(game["matchedProduct"]["developer"], "ConcernedApe")
        self.assertEqual(game["matchDecision"]["status"], "ApprovedCandidate")
        self.assertEqual(game["matchDecision"]["titleMatchSource"], "Stardew Valley")
        self.assertEqual(updated["games"][0]["products"][0]["offerType"], "BaseGame")

    def test_rejects_wrong_canonical_game_match(self):
        self.catalog["games"][0]["title"] = "Terraria"
        self.catalog["games"][0]["aliases"] = []
        metadata = catalog_import.verified_product(self.raw, "com.chucklefish.stardewvalley")
        _, game = catalog_import.updated_catalog(
            self.catalog,
            "stardew-valley",
            "com.chucklefish.stardewvalley",
            metadata,
        )
        self.assertEqual(game["matchDecision"]["status"], "Rejected")

    def test_rejects_matching_title_with_different_developer(self):
        self.catalog["games"][0]["developers"] = ["Different Studio"]
        metadata = catalog_import.verified_product(self.raw, "com.chucklefish.stardewvalley")
        decision = catalog_import.catalog_matcher.evaluate(self.catalog["games"][0], metadata)
        self.assertEqual(decision["status"], "Rejected")
        self.assertIn(
            "Developer or publisher differs from the canonical game",
            decision["reasons"],
        )

    def test_approves_official_publisher_when_store_developer_differs(self):
        self.catalog["games"][0]["publishers"] = ["505 Games"]
        metadata = catalog_import.verified_product(
            self.raw,
            "com.chucklefish.stardewvalley",
        )
        metadata["developer"] = "505 Games Srl"
        decision = catalog_import.catalog_matcher.evaluate(
            self.catalog["games"][0],
            metadata,
        )
        self.assertEqual(decision["status"], "ApprovedCandidate")
        self.assertFalse(decision["developerMatched"])
        self.assertTrue(decision["publisherMatched"])

    def test_normalizes_regional_official_publisher_name(self):
        self.catalog["games"][0]["publishers"] = ["505 Games"]
        metadata = catalog_import.verified_product(
            self.raw,
            "com.chucklefish.stardewvalley",
        )
        metadata["developer"] = "505 Games (US), Inc."
        decision = catalog_import.catalog_matcher.evaluate(
            self.catalog["games"][0],
            metadata,
        )
        self.assertEqual(decision["status"], "ApprovedCandidate")
        self.assertTrue(decision["publisherMatched"])

    def test_missing_developer_requires_explicit_review(self):
        self.catalog["games"][0]["developers"] = []
        metadata = catalog_import.verified_product(self.raw, "com.chucklefish.stardewvalley")
        _, preview = catalog_import.updated_catalog(
            self.catalog,
            "stardew-valley",
            "com.chucklefish.stardewvalley",
            metadata,
        )
        self.assertEqual(preview["matchDecision"]["status"], "NeedsReview")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit acknowledgement"):
                catalog_import.import_game(
                    path,
                    self.raw,
                    "com.chucklefish.stardewvalley",
                    "stardew-valley",
                    True,
                )

    def test_rejects_guide_offer_even_when_developer_matches(self):
        metadata = catalog_import.verified_product(self.raw, "com.chucklefish.stardewvalley")
        metadata["title"] = "Stardew Valley Guide"
        metadata["excludedWords"] = ["guide"]
        decision = catalog_import.catalog_matcher.evaluate(self.catalog["games"][0], metadata)
        self.assertEqual(decision["status"], "Rejected")

    def test_apply_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            catalog_import.import_game(
                path,
                self.raw,
                "com.chucklefish.stardewvalley",
                "stardew-valley",
                True,
            )
            self.assertTrue(path.with_suffix(".json.bak").exists())

    def test_rejects_package_already_connected_to_another_game(self):
        metadata = catalog_import.verified_product(
            self.raw,
            "com.chucklefish.stardewvalley",
        )
        self.catalog["games"][0]["products"] = [{
            "store": "GooglePlay",
            "productId": "com.chucklefish.stardewvalley",
        }]
        self.catalog["games"].append({
            "id": "different-game",
            "title": "Different Game",
            "platforms": ["Android"],
            "products": [],
        })
        with self.assertRaisesRegex(ValueError, "already belongs"):
            catalog_import.updated_catalog(
                self.catalog,
                "different-game",
                "com.chucklefish.stardewvalley",
                metadata,
            )


if __name__ == "__main__":
    unittest.main()
