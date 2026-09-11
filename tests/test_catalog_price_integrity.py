import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import audit_catalog_price_integrity as integrity


class CatalogPriceIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.catalog = root / "catalog.json"
        self.database = root / "prices.db"
        self.catalog.write_text(json.dumps({
            "schemaVersion": 4,
            "games": [{
                "id": "test-game",
                "title": "Test Game",
                "platforms": ["Windows"],
                "products": [{
                    "store": "Steam",
                    "productId": "10",
                    "productUrl": "https://example.com/10",
                    "platforms": ["Windows"],
                    "region": "KR",
                    "edition": "Standard",
                    "offerType": "BaseGame",
                }],
            }],
        }), encoding="utf-8")
        with sqlite3.connect(self.database) as connection:
            connection.executescript("""
                CREATE TABLE store_products(
                    store TEXT,
                    external_product_id TEXT,
                    game_id TEXT,
                    purchasable INTEGER,
                    last_successful_check_at TEXT
                );
                CREATE TABLE product_platforms(
                    store TEXT,
                    external_product_id TEXT,
                    platform TEXT
                );
            """)

    def tearDown(self):
        self.directory.cleanup()

    def test_reports_catalog_product_without_price(self):
        result = integrity.audit(self.catalog, self.database)
        self.assertEqual(result["counts"], {"MISSING_PRICE": 1})

    def test_reports_stale_unpurchasable_and_platform_mismatch(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO store_products VALUES(?, ?, ?, ?, ?)",
                ("Steam", "10", "test-game", 0, "2020-01-01T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO product_platforms VALUES(?, ?, ?)",
                ("Steam", "10", "Android"),
            )
        result = integrity.audit(self.catalog, self.database)
        self.assertEqual(result["counts"]["STALE_PRICE"], 1)
        self.assertEqual(result["counts"]["NOT_PURCHASABLE"], 1)
        self.assertEqual(result["counts"]["PLATFORM_MISMATCH"], 1)

    def test_matches_catalog_and_database_store_name_variants(self):
        document = json.loads(self.catalog.read_text(encoding="utf-8"))
        document["games"].append({
            "id": "mobile-game",
            "title": "Mobile Game",
            "platforms": ["Android"],
            "products": [{
                "store": "GooglePlay",
                "productId": "com.example.mobilegame",
                "productUrl": "https://play.google.com/store/apps/details?id=com.example.mobilegame",
                "platforms": ["Android"],
                "region": "KR",
                "edition": "Standard",
                "offerType": "BaseGame",
            }],
        })
        self.catalog.write_text(json.dumps(document), encoding="utf-8")
        checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO store_products VALUES(?, ?, ?, ?, ?)",
                (
                    "Google Play",
                    "com.example.mobilegame",
                    "mobile-game",
                    1,
                    checked_at,
                ),
            )
            connection.execute(
                "INSERT INTO product_platforms VALUES(?, ?, ?)",
                ("Google Play", "com.example.mobilegame", "Android"),
            )
        result = integrity.audit(self.catalog, self.database)
        mobile_issues = [
            entry
            for entry in result["issues"]
            if entry["productId"] == "com.example.mobilegame"
        ]
        self.assertEqual(mobile_issues, [])

    def test_matches_catalog_and_database_platform_name_variants(self):
        document = json.loads(self.catalog.read_text(encoding="utf-8"))
        document["games"].append({
            "id": "console-game",
            "title": "Console Game",
            "platforms": ["NintendoSwitch"],
            "products": [{
                "store": "NintendoEShop",
                "productId": "70010000000000",
                "productUrl": "https://www.nintendo.com/store/products/console-game-switch/",
                "platforms": ["NintendoSwitch"],
                "region": "KR",
                "edition": "Standard",
                "offerType": "BaseGame",
            }],
        })
        self.catalog.write_text(json.dumps(document), encoding="utf-8")
        checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO store_products VALUES(?, ?, ?, ?, ?)",
                (
                    "Nintendo eShop",
                    "70010000000000",
                    "console-game",
                    1,
                    checked_at,
                ),
            )
            connection.execute(
                "INSERT INTO product_platforms VALUES(?, ?, ?)",
                ("Nintendo eShop", "70010000000000", "Nintendo Switch"),
            )
        result = integrity.audit(self.catalog, self.database)
        console_issues = [
            entry
            for entry in result["issues"]
            if entry["productId"] == "70010000000000"
        ]
        self.assertEqual(console_issues, [])


if __name__ == "__main__":
    unittest.main()
