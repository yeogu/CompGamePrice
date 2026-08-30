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
            "games": [{"id": "stardew-valley", "title": "Stardew Valley", "platforms": ["Windows"], "products": []}],
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
        self.assertEqual(updated["games"][0]["products"][0]["offerType"], "BaseGame")

    def test_rejects_wrong_canonical_game_match(self):
        self.catalog["games"][0]["title"] = "Terraria"
        metadata = catalog_import.verified_product(self.raw, "com.chucklefish.stardewvalley")
        with self.assertRaisesRegex(ValueError, "does not match"):
            catalog_import.updated_catalog(
                self.catalog,
                "stardew-valley",
                "com.chucklefish.stardewvalley",
                metadata,
            )

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


if __name__ == "__main__":
    unittest.main()
