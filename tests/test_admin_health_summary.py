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
            (root / "collection-scheduler-status.json").write_text(
                json.dumps(
                    {
                        "job": "collection",
                        "enabled": False,
                        "status": "DISABLED",
                        "updatedAt": "2026-01-02T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            (root / "backup-scheduler-status.json").write_text(
                json.dumps(
                    {
                        "job": "backup",
                        "enabled": True,
                        "status": "SUCCEEDED",
                        "lastBackup": "game_prices.db",
                        "updatedAt": "2026-01-02T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            (root / "artwork-quality-status.json").write_text(
                json.dumps(
                    {
                        "checkedAt": "2026-01-02T00:00:00Z",
                        "candidates": 4,
                        "attempted": 3,
                        "updated": 2,
                        "qualityRejected": 1,
                        "failed": [{"gameId": "broken"}],
                        "decisions": [
                            {
                                "gameId": "ok",
                                "status": "UPDATED",
                                "score": 92.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshots = root / "collection-snapshots"
            snapshots.mkdir()
            (snapshots / "steam_pipeline_run.json").write_text(
                json.dumps(
                    {
                        "startedAt": "2026-01-02T00:00:00Z",
                        "finishedAt": "2026-01-02T00:01:00Z",
                        "catalogTargets": 120,
                        "targets": 40,
                        "collected": 39,
                        "retryCount": 2,
                        "failures": [{"appId": "1", "error": "Steam HTTP 429"}],
                    }
                ),
                encoding="utf-8",
            )
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
                    CREATE TABLE catalog_sync_runs(
                        id INTEGER PRIMARY KEY,
                        provider TEXT,
                        status TEXT,
                        started_at TEXT,
                        finished_at TEXT,
                        processed_count INTEGER,
                        accepted_count INTEGER,
                        review_count INTEGER,
                        skipped_count INTEGER,
                        failed_count INTEGER
                    );
                    INSERT INTO catalog_sync_runs VALUES(
                        1, 'Steam', 'SUCCEEDED',
                        '2099-01-01T00:00:00Z', '2099-01-01T00:01:00Z',
                        20, 3, 2, 14, 1
                    );
                    """
                )
            result = admin_health_summary.summary(catalog, database)
            self.assertEqual(result["metadata"], {"complete": 1, "incomplete": 1, "total": 2})
            self.assertEqual(result["collection"]["recentFailures"], 1)
            self.assertEqual(result["collection"]["steamPipeline"]["targets"], 40)
            self.assertEqual(result["collection"]["steamPipeline"]["failed"], 1)
            self.assertEqual(
                result["collection"]["steamPipeline"]["lastError"],
                "Steam HTTP 429",
            )
            self.assertEqual(result["notifications"]["pending"], 1)
            self.assertEqual(result["emails"]["pending"], 0)
            self.assertEqual(result["automation"]["collection"]["status"], "DISABLED")
            self.assertEqual(result["automation"]["backup"]["status"], "SUCCEEDED")
            self.assertEqual(result["artwork"]["updated"], 2)
            self.assertEqual(result["artwork"]["broken"], 1)
            self.assertEqual(result["artwork"]["decisions"][0]["gameId"], "ok")
            steam = next(store for store in result["stores"] if store["store"] == "Steam")
            self.assertEqual(steam["stalePrices"], 1)
            self.assertEqual(steam["pendingReviews"], 1)
            self.assertEqual(steam["registeredProducts"], 0)
            self.assertEqual(steam["catalogProcessed"], 20)
            self.assertEqual(steam["catalogAccepted"], 3)
            self.assertEqual(steam["catalogReview"], 2)
            self.assertEqual(steam["catalogSkippedOrRejected"], 14)
            self.assertEqual(steam["catalogFailed"], 1)
            self.assertEqual(steam["catalogAddedLast7Days"], 3)


if __name__ == "__main__":
    unittest.main()
