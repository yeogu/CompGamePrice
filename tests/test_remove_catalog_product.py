import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import remove_catalog_product


class RemoveCatalogProductTest(unittest.TestCase):
    def test_removes_last_product_and_records_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            database = root / "catalog.db"
            catalog.write_text(json.dumps({
                "schemaVersion": 4,
                "games": [{
                    "id": "wrong-game",
                    "title": "Wrong Game",
                    "products": [{"store": "Steam", "productId": "10"}],
                }],
            }), encoding="utf-8")

            result = remove_catalog_product.remove_product(
                catalog,
                database,
                "Steam",
                "10",
                True,
            )

            self.assertTrue(result["removedGame"])
            self.assertEqual(json.loads(catalog.read_text())["games"], [])
            with sqlite3.connect(database) as connection:
                audit = connection.execute(
                    "SELECT action, outcome FROM catalog_change_audit"
                ).fetchone()
            self.assertEqual(audit, ("DISCONNECT_STORE_PRODUCT", "APPLIED"))

    def test_preview_does_not_change_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            database = root / "catalog.db"
            original = {"schemaVersion": 4, "games": [{
                "id": "game",
                "title": "Game",
                "products": [
                    {"store": "Steam", "productId": "10"},
                    {"store": "GooglePlay", "productId": "package.game"},
                ],
            }]}
            catalog.write_text(json.dumps(original), encoding="utf-8")

            result = remove_catalog_product.remove_product(
                catalog,
                database,
                "Steam",
                "10",
                False,
            )

            self.assertFalse(result["removedGame"])
            self.assertEqual(json.loads(catalog.read_text()), original)


if __name__ == "__main__":
    unittest.main()
