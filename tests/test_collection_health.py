import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "collection_health", ROOT / "tools" / "check_collection_health.py"
)
collection_health = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collection_health)


class CollectionHealthTest(unittest.TestCase):
    def create_database(self, path: Path, status: str, checked_at: str) -> None:
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE crawl_runs (
                    id INTEGER PRIMARY KEY, store TEXT, status TEXT,
                    started_at TEXT, error_message TEXT
                );
                CREATE TABLE store_products (
                    store TEXT, external_product_id TEXT,
                    last_successful_check_at TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO crawl_runs VALUES(1, 'Steam', ?, ?, NULL)",
                (status, checked_at),
            )
            connection.execute(
                "INSERT INTO store_products VALUES('Steam', '413150', ?)",
                (checked_at,),
            )

    def test_reports_recent_success_as_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prices.db"
            self.create_database(database, "SUCCEEDED", "2026-08-29T00:00:00.000Z")
            result = collection_health.collection_health(
                database, now=datetime(2026, 8, 29, 1, tzinfo=timezone.utc)
            )
            self.assertTrue(result["healthy"])

    def test_reports_failure_and_stale_product(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prices.db"
            self.create_database(database, "FAILED", "2026-08-20T00:00:00.000Z")
            result = collection_health.collection_health(
                database, now=datetime(2026, 8, 29, 1, tzinfo=timezone.utc)
            )
            self.assertFalse(result["healthy"])
            self.assertEqual(result["failedProviders"][0]["store"], "Steam")
            self.assertEqual(result["staleProducts"][0]["productId"], "413150")


if __name__ == "__main__":
    unittest.main()
