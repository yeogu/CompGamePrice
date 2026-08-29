import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "steam_catalog_batch_import",
    ROOT / "tools" / "batch_add_steam_catalog_games.py",
)
batch_import = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(batch_import)


class SteamCatalogBatchImportTest(unittest.TestCase):
    def test_loads_unique_ids_and_ignores_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "steam_app_ids.txt"
            path.write_text(
                "413150 # Stardew Valley\n\n105600,terraria\n",
                encoding="utf-8",
            )
            self.assertEqual(
                batch_import.load_targets(path),
                [("413150", None), ("105600", "terraria")],
            )

    def test_rejects_duplicate_or_non_numeric_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "steam_app_ids.txt"
            path.write_text("413150\n413150\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                batch_import.load_targets(path)
            path.write_text("not-an-id\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "app_id"):
                batch_import.load_targets(path)

    def test_isolates_rejected_product_without_partial_catalog(self):
        valid = (ROOT / "tests/fixtures/steam_appdetails_413150.json").read_bytes()
        invalid_payload = json.loads(valid)
        invalid_payload["413150"]["data"]["type"] = "dlc"
        invalid = json.dumps(invalid_payload).encode()

        def fetcher(app_id):
            return valid if app_id == "413150" else invalid.replace(b"413150", b"999999")

        original = {"schemaVersion": 4, "games": []}
        updated, accepted, rejected = batch_import.prepare_batch(
            original,
            [("413150", None), ("999999", None)],
            fetcher,
            0,
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected[0]["appId"], "999999")
        self.assertEqual(original["games"], [])
        self.assertEqual(len(updated["games"]), 1)


if __name__ == "__main__":
    unittest.main()
