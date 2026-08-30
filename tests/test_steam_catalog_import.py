import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "steam_catalog_import", ROOT / "tools" / "add_steam_catalog_game.py"
)
steam_catalog_import = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(steam_catalog_import)


class SteamCatalogImportTest(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / "tests/fixtures/steam_appdetails_413150.json").read_bytes()

    def catalog(self) -> dict:
        return {"schemaVersion": 4, "games": []}

    def test_preview_builds_standard_base_game_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game_catalog.json"
            path.write_text(json.dumps(self.catalog()), encoding="utf-8")
            before = path.read_bytes()
            game = steam_catalog_import.import_game(path, self.raw, "413150", False)
            self.assertEqual(game["id"], "stardew-valley")
            self.assertEqual(game["platforms"], ["Windows", "macOS", "Linux"])
            self.assertEqual(game["genres"], ["Indie", "Simulation", "RPG"])
            self.assertEqual(game["tags"], ["Multiplayer", "Controller"])
            self.assertEqual(game["aliases"], [])
            self.assertEqual(game["developers"], ["ConcernedApe"])
            self.assertEqual(game["publishers"], ["ConcernedApe"])
            self.assertEqual(game["products"][0]["offerType"], "BaseGame")
            self.assertEqual(path.read_bytes(), before)

    def test_apply_updates_catalog_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game_catalog.json"
            path.write_text(json.dumps(self.catalog()), encoding="utf-8")
            steam_catalog_import.import_game(path, self.raw, "413150", True)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["games"][0]["title"], "Stardew Valley")
            self.assertTrue(path.with_suffix(".json.bak").is_file())

    def test_rejects_non_game_and_duplicate_product(self):
        payload = json.loads(self.raw)
        payload["413150"]["data"]["type"] = "dlc"
        with self.assertRaisesRegex(ValueError, "base games"):
            steam_catalog_import.catalog_game(json.dumps(payload).encode(), "413150")

        payload = json.loads(self.raw)
        payload["413150"]["data"]["is_free"] = True
        with self.assertRaisesRegex(ValueError, "Free Steam games"):
            steam_catalog_import.catalog_game(json.dumps(payload).encode(), "413150")

        game = steam_catalog_import.catalog_game(self.raw, "413150")
        catalog = self.catalog()
        catalog["games"].append(copy.deepcopy(game))
        with self.assertRaisesRegex(ValueError, "already exists"):
            steam_catalog_import.updated_catalog(catalog, game)


if __name__ == "__main__":
    unittest.main()
