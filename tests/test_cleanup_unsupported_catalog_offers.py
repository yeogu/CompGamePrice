import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import cleanup_unsupported_catalog_offers as cleanup


class CleanupUnsupportedCatalogOffersTest(unittest.TestCase):
    def catalog(self):
        return {
            "schemaVersion": 4,
            "games": [{
                "id": "it-takes-two",
                "title": "It Takes Two",
                "products": [
                    {
                        "store": "PlayStationStore",
                        "productId": "IT-TAKES-TWO-FRIEND-PASS",
                        "productUrl": "https://store.playstation.com/product/friend-pass",
                    },
                    {
                        "store": "PlayStationStore",
                        "productId": "ITTAKESTWORETAIL",
                        "productUrl": "https://store.playstation.com/product/retail",
                    },
                ],
            }],
        }

    def test_dry_run_finds_only_confident_unsupported_offer(self):
        result = cleanup.audit(self.catalog())
        self.assertEqual(result["checkedProducts"], 2)
        self.assertEqual(result["unsupportedCount"], 1)
        self.assertEqual(
            result["unsupported"][0]["productId"],
            "IT-TAKES-TWO-FRIEND-PASS",
        )

    def test_official_playstation_verification_can_identify_opaque_id(self):
        document = self.catalog()
        document["games"][0]["products"][0]["productId"] = "OPAQUE-ID"
        with mock.patch.object(cleanup.storefront_catalog, "fetch_product", return_value=b"page"), mock.patch.object(
            cleanup.storefront_catalog,
            "verified_product",
            side_effect=ValueError("PlayStation demo or friend-pass product is not supported"),
        ):
            result = cleanup.audit(document, verify_playstation=True)
        self.assertEqual(result["unsupportedCount"], 2)

    def test_apply_removes_offer_and_records_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            database_path = root / "catalog.db"
            catalog_path.write_text(json.dumps(self.catalog()), encoding="utf-8")
            result = cleanup.cleanup(catalog_path, database_path, True)
            remaining = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertTrue(result["applied"])
            self.assertEqual(
                remaining["games"][0]["products"][0]["productId"],
                "ITTAKESTWORETAIL",
            )
            with sqlite3.connect(database_path) as connection:
                action, outcome = connection.execute(
                    "SELECT action, outcome FROM catalog_change_audit"
                ).fetchone()
            self.assertEqual((action, outcome), ("DISCONNECT_STORE_PRODUCT", "APPLIED"))


if __name__ == "__main__":
    unittest.main()
