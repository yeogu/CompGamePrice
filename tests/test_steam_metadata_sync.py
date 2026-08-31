import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import sync_steam_metadata


class SteamMetadataSyncTest(unittest.TestCase):
    def test_automatically_fills_only_missing_verified_fields(self):
        raw = (ROOT / "tests/fixtures/steam_appdetails_413150.json").read_bytes()
        catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "stardew-valley",
                "title": "Stardew Valley",
                "products": [{"store": "Steam", "productId": "413150"}],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            database = root / "prices.db"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            result = sync_steam_metadata.synchronize(
                catalog_path,
                database,
                fetcher=lambda app_id: raw,
            )
            self.assertEqual(result["autoApplied"], 1)
            self.assertEqual(result["discovered"], 0)
            self.assertEqual(result["pendingReviews"], [])
            updated = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["games"][0]["developers"], ["ConcernedApe"])
            self.assertEqual(updated["games"][0]["publishers"], ["ConcernedApe"])
            with sqlite3.connect(database) as connection:
                audit = connection.execute(
                    """
                    SELECT actor, action, outcome
                    FROM catalog_change_audit
                    """
                ).fetchone()
            self.assertEqual(
                audit,
                ("steam-metadata-sync", "UPDATE_GAME_METADATA", "APPLIED"),
            )
            repeated = sync_steam_metadata.synchronize(
                catalog_path,
                database,
                fetcher=lambda app_id: raw,
            )
            self.assertEqual(repeated["autoApplied"], 0)
            self.assertEqual(repeated["pendingReviews"], [])

    def test_existing_identity_conflict_requires_approval(self):
        raw = (ROOT / "tests/fixtures/steam_appdetails_413150.json").read_bytes()
        catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "stardew-valley",
                "title": "Stardew Valley",
                "developers": ["Different Studio"],
                "products": [{"store": "Steam", "productId": "413150"}],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            database = root / "prices.db"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            result = sync_steam_metadata.synchronize(
                catalog_path,
                database,
                fetcher=lambda app_id: raw,
            )
            self.assertEqual(result["autoApplied"], 0)
            self.assertEqual(result["discovered"], 1)
            self.assertEqual(
                result["pendingReviews"][0]["diff"]["developers"]["before"],
                ["Different Studio"],
            )
            unchanged = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(
                unchanged["games"][0]["developers"],
                ["Different Studio"],
            )

    def test_partial_failure_does_not_remove_other_proposals(self):
        catalog = {
            "schemaVersion": 4,
            "games": [
                {"id": "one", "title": "One", "products": [{"store": "Steam", "productId": "1"}]},
                {"id": "two", "title": "Two", "products": [{"store": "Steam", "productId": "2"}]},
            ],
        }
        fixture = json.dumps({
            "1": {
                "success": True,
                "data": {
                    "type": "game",
                    "developers": ["Studio"],
                    "publishers": ["Publisher"],
                    "genres": [],
                },
            },
        }).encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            def fetch(app_id):
                if app_id == "2":
                    raise TimeoutError("timed out")
                return fixture
            result = sync_steam_metadata.synchronize(
                path,
                root / "prices.db",
                fetcher=fetch,
            )
            self.assertEqual(result["autoApplied"], 1)
            self.assertEqual(result["discovered"], 0)
            self.assertEqual(result["failed"][0]["gameId"], "two")


if __name__ == "__main__":
    unittest.main()
