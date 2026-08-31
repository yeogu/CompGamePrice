import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import update_catalog_game_metadata as metadata_update


class CatalogMetadataUpdateTest(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "terraria",
                "title": "Terraria",
                "platforms": ["Windows"],
                "products": [],
            }],
        }

    def test_preview_reports_only_changed_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            result = metadata_update.update_metadata(
                path,
                "terraria",
                {
                    "title": "Terraria",
                    "developers": [" Re-Logic ", "Re-Logic"],
                    "publishers": ["505 Games"],
                },
                False,
            )
            self.assertEqual(set(result["diff"]), {"developers", "publishers"})
            self.assertEqual(result["game"]["developers"], ["Re-Logic"])
            self.assertNotIn("developers", json.loads(path.read_text())["games"][0])

    def test_apply_is_audited_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            database = Path(directory) / "tracker.db"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            payload = {
                "developers": ["Re-Logic"],
                "publishers": ["505 Games"],
            }
            first = metadata_update.update_metadata(
                path,
                "terraria",
                payload,
                True,
                database,
            )
            second = metadata_update.update_metadata(
                path,
                "terraria",
                payload,
                True,
                database,
            )
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT action, outcome FROM catalog_change_audit ORDER BY id"
                ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("UPDATE_GAME_METADATA", "APPLIED"),
                    ("UPDATE_GAME_METADATA", "NO_OP"),
                ],
            )

    def test_rejects_unknown_or_invalid_fields(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            metadata_update.validated_changes({"products": []})
        with self.assertRaisesRegex(ValueError, "non-empty"):
            metadata_update.validated_changes({"developers": [""]})


if __name__ == "__main__":
    unittest.main()
