import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import admin_health_summary


class AdminHealthSummaryTest(unittest.TestCase):
    def test_combines_metadata_collection_and_delivery_health(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            database = root / "prices.db"
            catalog.write_text(json.dumps({
                "schemaVersion": 4,
                "games": [
                    {"id": "ok", "title": "OK", "developers": ["D"], "publishers": ["P"], "products": []},
                    {"id": "missing", "title": "Missing", "products": []},
                ],
            }), encoding="utf-8")
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE crawl_runs(
                        id INTEGER PRIMARY KEY, store TEXT, status TEXT,
                        error_message TEXT, started_at TEXT
                    );
                    INSERT INTO crawl_runs VALUES(1, 'Steam', 'FAILED', 'timeout', '2026-01-01T00:00:00Z');
                    CREATE TABLE notification_outbox(
                        notification_id INTEGER PRIMARY KEY, channel TEXT, status TEXT
                    );
                    INSERT INTO notification_outbox VALUES(1, 'email', 'PENDING');
                    CREATE TABLE store_products(
                        store TEXT,
                        last_successful_check_at TEXT
                    );
                    INSERT INTO store_products VALUES('Steam', '2020-01-01T00:00:00Z');
                    CREATE TABLE catalog_sync_review(
                        provider TEXT,
                        status TEXT
                    );
                    INSERT INTO catalog_sync_review VALUES('Steam', 'PENDING');
                    """
                )
            result = admin_health_summary.summary(catalog, database)
            self.assertEqual(result["metadata"], {"complete": 1, "incomplete": 1, "total": 2})
            self.assertEqual(result["collection"]["recentFailures"], 1)
            self.assertEqual(result["notifications"]["pending"], 1)
            steam = next(store for store in result["stores"] if store["store"] == "Steam")
            self.assertEqual(steam["stalePrices"], 1)
            self.assertEqual(steam["pendingReviews"], 1)
            self.assertEqual(steam["registeredProducts"], 0)


if __name__ == "__main__":
    unittest.main()
