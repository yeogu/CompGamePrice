import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "catalog_sync_pipeline",
    ROOT / "tools/run_catalog_sync_pipeline.py",
)
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class CatalogSyncPipelineTest(unittest.TestCase):
    def save_price(self, database, app_id="10", game_id="new"):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS store_products(store TEXT,external_product_id TEXT,game_id TEXT,last_successful_check_at TEXT)")
            connection.execute("INSERT INTO store_products VALUES ('Steam',?,?,datetime('now'))", (app_id, game_id))

    def run_pipeline(self, accepted, collection_exit_code=0):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        database = root / "catalog.db"
        commands = []
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"schemaVersion": 4, "games": [
            {"id": "new", "title": "New", "products": [{"store": "Steam", "productId": "10"}]},
            {"id": "old", "title": "Old", "products": [{"store": "Steam", "productId": "20"}]},
        ]}))

        def synchronize(catalog, database_path, batch_size):
            with sqlite3.connect(database_path) as connection:
                pipeline.catalog_sync.initialize_state(connection)
            return {
                "status": "SUCCEEDED",
                "accepted": accepted,
                "acceptedAppIds": ["10"] if accepted else [],
            }

        def run(command, check, env):
            selected = json.loads(Path(command[command.index("--catalog") + 1]).read_text())
            self.assertEqual([g["id"] for g in selected["games"]], ["new"])
            self.assertEqual(env["GAME_PRICE_CATALOG_PATH"], command[command.index("--catalog") + 1])
            commands.append((command, check, env))
            if collection_exit_code == 0:
                self.save_price(database)
            return subprocess.CompletedProcess(command, collection_exit_code)

        report, exit_code = pipeline.run_pipeline(
            ROOT,
            root / "catalog.json",
            database,
            ROOT / "build/game_price_tracker",
            root / "snapshots",
            20,
            synchronizer=synchronize,
            command_runner=run,
        )
        return report, exit_code, commands, database

    def test_collects_prices_after_new_game_registration(self):
        report, exit_code, commands, database = self.run_pipeline(1)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["priceCollection"]["status"], "SUCCEEDED")
        self.assertEqual(len(commands), 1)
        self.assertIn("run_steam_pipeline.py", commands[0][0][1])
        status = pipeline.catalog_sync.synchronization_status(database)
        self.assertEqual(status["priceCollection"]["status"], "SUCCEEDED")

    def test_skips_immediate_collection_when_no_game_was_registered(self):
        report, exit_code, commands, _ = self.run_pipeline(0)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["priceCollection"]["status"], "NOT_REQUIRED")
        self.assertEqual(commands, [])

    def test_records_price_collection_failure_for_next_scheduled_retry(self):
        report, exit_code, _, database = self.run_pipeline(1, 1)
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["priceCollection"]["status"], "FAILED")
        status = pipeline.catalog_sync.synchronization_status(database)
        self.assertEqual(status["priceCollection"]["exitCode"], 1)

    def test_retries_previous_price_collection_failure_without_new_games(self):
        report, _, _, database = self.run_pipeline(1, 1)
        self.assertEqual(report["priceCollection"]["status"], "FAILED")
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE catalog_initial_prices SET next_attempt_at=0")

        def synchronize(catalog, database_path, batch_size):
            return {"status": "SUCCEEDED", "accepted": 0, "acceptedAppIds": []}

        commands = []

        def run(command, check, env):
            commands.append(command)
            self.save_price(database)
            return subprocess.CompletedProcess(command, 0)

        retried, exit_code = pipeline.run_pipeline(
            ROOT,
            database.parent / "catalog.json",
            database,
            ROOT / "build/game_price_tracker",
            database.parent / "snapshots",
            20,
            synchronizer=synchronize,
            command_runner=run,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(retried["priceCollection"]["status"], "SUCCEEDED")
        self.assertEqual(len(commands), 1)

    def test_failed_registration_does_not_report_success_when_price_not_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def synchronize(*args):
                return {"status": "FAILED", "accepted": 0, "acceptedAppIds": [], "failed": 5}
            report, code = pipeline.run_pipeline(ROOT, root / "catalog.json", root / "db", Path("tracker"), root / "out", 20, synchronizer=synchronize)
            self.assertEqual(code, 1)
            self.assertEqual(report["priceCollection"]["status"], "NOT_REQUIRED")

    def test_partial_success_prunes_saved_prices_and_defers_only_failure(self):
        _, _, _, database = self.run_pipeline(0)
        def run(command, check, env):
            self.save_price(database)
            return subprocess.CompletedProcess(command, 1)
        report, code = pipeline.collect_registered_prices(ROOT, database.parent / "catalog.json", database, Path("tracker"), database.parent / "output", ["10", "20"], run)
        self.assertEqual((code, report["confirmed"]), (2, 1))
        with sqlite3.connect(database) as connection:
            self.assertEqual([r[0] for r in connection.execute("SELECT app_id FROM catalog_initial_prices")], ["20"])
        def forbidden(*args, **kwargs):
            self.fail("deferred or already priced products must not be fetched")
        report, code = pipeline.collect_registered_prices(ROOT, database.parent / "catalog.json", database, Path("tracker"), database.parent / "output", [], forbidden)
        self.assertEqual(report["targets"], 0)

    def test_success_exit_without_persisted_price_is_failure(self):
        _, _, _, database = self.run_pipeline(0)
        report, code = pipeline.collect_registered_prices(ROOT, database.parent / "catalog.json", database, Path("tracker"), database.parent / "output", ["10"], lambda command, **kwargs: subprocess.CompletedProcess(command, 0))
        self.assertEqual((code, report["confirmed"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
