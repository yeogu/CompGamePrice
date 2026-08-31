import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import sync_steam_metadata


class SteamMetadataSyncTest(unittest.TestCase):
    def test_discovers_diff_and_applies_only_after_approval(self):
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
            self.assertEqual(result["discovered"], 1)
            review = result["pendingReviews"][0]
            self.assertEqual(review["proposed"]["developers"], ["ConcernedApe"])
            unchanged = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertNotIn("developers", unchanged["games"][0])
            resolved = sync_steam_metadata.resolve(
                catalog_path,
                database,
                "stardew-valley",
                "APPROVED",
            )
            self.assertEqual(resolved["pendingReviews"], [])
            updated = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["games"][0]["developers"], ["ConcernedApe"])
            self.assertEqual(updated["games"][0]["publishers"], ["ConcernedApe"])

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
            self.assertEqual(result["discovered"], 1)
            self.assertEqual(result["failed"][0]["gameId"], "two")


if __name__ == "__main__":
    unittest.main()
