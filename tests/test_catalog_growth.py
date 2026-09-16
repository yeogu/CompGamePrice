import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import catalog_growth
import sync_steam_catalog
import admin_health_summary


class CatalogGrowthTest(unittest.TestCase):
    def run_growth(self, discovery=None, pipeline=None, max_batches=2):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            return catalog_growth.run_growth(ROOT, root / "tracker", root / "db", root / "catalog", root / "out", 100,
                max_batches=max_batches, discoverer=discovery or (lambda *a, **kw: {"status": "SUCCEEDED"}), pipeline_runner=pipeline)

    def test_continues_registration_despite_discovery_and_initial_price_failure(self):
        batches = []
        def discovery(*args, **kwargs):
            raise OSError("search temporarily unavailable")
        def pipeline(*args):
            batches.append(1)
            return {"status": "SUCCEEDED", "processed": 100, "accepted": 100,
                    "priceCollection": {"status": "FAILED"}}, 1
        result = self.run_growth(discovery, pipeline)
        self.assertEqual(len(batches), 2)
        self.assertEqual(result[0]["outcome"], "FAILED")

    def test_empty_queue_and_registration_failure_stop_more_batches(self):
        for processed, failed in [(0, 0), (100, 5)]:
            with self.subTest(processed=processed):
                batches = []
                def pipeline(*args):
                    batches.append(1)
                    return {"status": "SUCCEEDED", "processed": processed, "failed": failed}, 0
                self.run_growth(pipeline=pipeline)
                self.assertEqual(len(batches), 1)

    def test_large_backlog_is_drained_before_more_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "db"
            with sqlite3.connect(database) as connection:
                sync_steam_catalog.initialize_state(connection)
                connection.executemany("INSERT INTO catalog_discovery_candidates(provider,external_product_id,title,source,priority,status,discovered_at) VALUES ('Steam',?,'Game','test',1,'PENDING','2026-01-01')", [(str(i),) for i in range(1000)])
            def forbidden(*args, **kwargs):
                self.fail("must drain existing queue first")
            result = catalog_growth.run_growth(ROOT, root / "tracker", database, root / "catalog", root / "out", 100,
                max_batches=2, discoverer=forbidden, pipeline_runner=lambda *a: ({"status": "SUCCEEDED", "processed": 100}, 0))
            self.assertEqual(result[0]["report"]["status"], "BACKLOG")
            self.assertEqual(len(result), 3)

    def test_growth_dashboard_excludes_processed_and_registered_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "db"
            with sqlite3.connect(database) as connection:
                sync_steam_catalog.initialize_state(connection)
                connection.executemany("INSERT INTO catalog_discovery_candidates(provider,external_product_id,title,source,priority,status,discovered_at) VALUES ('Steam',?,'Game','test',1,'PENDING','2026-01-01')", [(str(i),) for i in range(4)])
                connection.execute("INSERT INTO catalog_sync_seen VALUES ('Steam','1','SKIPPED','2026-01-01')")
                connection.execute("INSERT INTO catalog_sync_retry VALUES ('Steam','2',1,'2099-01-01T00:00:00Z','timeout')")
            document = {"games": [{"id": "registered", "products": [{"store": "Steam", "productId": "0"}]}]}
            result = admin_health_summary.catalog_growth_summary(document, database)
            self.assertEqual((result["gameCount"], result["pendingCandidates"], result["retryDeferred"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
