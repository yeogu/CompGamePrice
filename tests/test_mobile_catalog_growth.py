import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import mobile_catalog_growth as growth


def metadata(**changes):
    return {"title": "Paid Adventure", "developer": "Example Studio", "priceMinor": 5500,
            "currency": "KRW", "isGame": True, "supportsTargetPlatform": True,
            "excludedWords": [], "platforms": ["iOS"], **changes}


class MobileGrowthTests(unittest.TestCase):
    def test_paid_registration_and_idempotency(self):
        for provider in ("AppleAppStore", "GooglePlay"):
            with self.subTest(provider=provider):
                catalog, result = growth.apply_candidate({"schemaVersion": 4, "games": []}, provider, "123", metadata())
                self.assertEqual(result["outcome"], "REGISTERED")
                self.assertEqual(len(catalog["games"]), 1)
                self.assertEqual(len(catalog["games"][0]["products"]), 1)
                again, result = growth.apply_candidate(catalog, provider, "123", metadata())
                self.assertEqual(again, catalog)
                self.assertEqual(result["outcome"], "EXISTING")

    def test_free_only_and_invalid_apps_not_registered(self):
        for changes in ({"priceMinor": 0}, {"isGame": False}, {"excludedWords": ["demo"]},
                        {"supportsTargetPlatform": False}, {"priceMinor": -1},
                        {"currency": "USD"}, {"platforms": ["macOS"]}):
            with self.subTest(changes=changes):
                catalog, result = growth.apply_candidate({"schemaVersion": 4, "games": []}, "AppleAppStore", "123", metadata(**changes))
                self.assertEqual(catalog["games"], [])
                self.assertIn(result["outcome"], {"EXCLUDED", "FREE_ONLY_EXCLUDED"})

    def test_free_cross_store_links_existing_game(self):
        catalog, _ = growth.apply_candidate({"schemaVersion": 4, "games": []}, "AppleAppStore", "123", metadata())
        catalog, result = growth.apply_candidate(catalog, "GooglePlay", "com.example.game", metadata(priceMinor=0))
        self.assertEqual(result["outcome"], "LINKED")
        self.assertEqual(len(catalog["games"]), 1)
        self.assertEqual(len(catalog["games"][0]["products"]), 2)

    def test_title_collision_is_not_new_game(self):
        catalog, _ = growth.apply_candidate({"schemaVersion": 4, "games": []}, "AppleAppStore", "123", metadata())
        updated, result = growth.apply_candidate(catalog, "GooglePlay", "other", metadata(developer="Different Company"))
        self.assertEqual(result["outcome"], "NEEDS_REVIEW")
        self.assertEqual(updated, catalog)

    def test_sequel_does_not_auto_link_to_original(self):
        catalog, _ = growth.apply_candidate({"schemaVersion": 4, "games": []}, "AppleAppStore", "123", metadata())
        updated, result = growth.apply_candidate(catalog, "GooglePlay", "sequel", metadata(title="Paid Adventure 2"))
        self.assertEqual(result["outcome"], "NEEDS_REVIEW")
        self.assertEqual(updated, catalog)

    def test_first_price_retry_is_durable_without_duplicate_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, database = root / "catalog.json", root / "state.db"
            catalog.write_text(json.dumps({"schemaVersion": 4, "games": []}))
            config = {**growth.STORE_CONFIG["AppleAppStore"],
                      "search": lambda *args: [{"externalProductId": "123"}],
                      "fetch": lambda *args: b"data", "metadata": lambda *args: metadata()}
            with patch.dict(growth.STORE_CONFIG, {"AppleAppStore": config}), patch.object(growth.time, "sleep"), \
                    patch.object(growth, "apple_paid_candidates", return_value=[]), \
                    patch.object(growth, "price_confirmed", return_value=True), \
                    patch("run_apple_pipeline.run_pipeline", side_effect=[1, 0]) as collect:
                self.assertEqual(growth.run("AppleAppStore", catalog, database, root / "tracker", root), 2)
                with sqlite3.connect(database) as db:
                    self.assertEqual(db.execute("SELECT price_pending FROM mobile_growth_candidates").fetchone()[0], 1)
                    db.execute("UPDATE mobile_growth_candidates SET checked_at=0")
                self.assertEqual(growth.run("AppleAppStore", catalog, database, root / "tracker", root), 0)
                self.assertEqual(len(json.loads(catalog.read_text())["games"]), 1)
                self.assertEqual(collect.call_count, 2)
                with sqlite3.connect(database) as db:
                    self.assertEqual(db.execute("SELECT price_pending FROM mobile_growth_candidates").fetchone()[0], 0)
                    runs = db.execute("SELECT status,registered_count,price_failed_count FROM mobile_growth_runs ORDER BY id").fetchall()
                    self.assertEqual(runs, [("PARTIAL", 1, 1), ("SUCCEEDED", 0, 0)])

    def test_success_requires_actual_recent_price(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"
            self.assertFalse(growth.price_confirmed(database, "AppleAppStore", "123", 100))
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE store_products(store,external_product_id,last_successful_check_at,currency,region,purchasable)")
                db.execute("INSERT INTO store_products VALUES('Apple App Store','123','1970-01-01T00:03:20Z','KRW','KR',1)")
            self.assertTrue(growth.price_confirmed(database, "AppleAppStore", "123", 100))
            self.assertFalse(growth.price_confirmed(database, "AppleAppStore", "123", 300))
            self.assertFalse(growth.price_confirmed(database, "AppleAppStore", "other", 100))


if __name__ == "__main__":
    unittest.main()
