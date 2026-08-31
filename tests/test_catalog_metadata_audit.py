import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_catalog_metadata as metadata_audit


class CatalogMetadataAuditTest(unittest.TestCase):
    def test_lists_incomplete_games_and_counts_complete_games(self):
        document = {
            "schemaVersion": 4,
            "games": [
                {
                    "id": "complete",
                    "title": "Complete",
                    "developers": ["Studio"],
                    "publishers": ["Publisher"],
                    "products": [],
                },
                {
                    "id": "incomplete",
                    "title": "Incomplete",
                    "developers": [],
                    "products": [{"store": "Steam"}],
                },
            ],
        }
        result = metadata_audit.audit(document)
        self.assertEqual(result["gameCount"], 2)
        self.assertEqual(result["completeCount"], 1)
        self.assertEqual(result["incompleteCount"], 1)
        self.assertEqual(
            result["games"][0]["missingFields"],
            ["developers", "publishers"],
        )


if __name__ == "__main__":
    unittest.main()
