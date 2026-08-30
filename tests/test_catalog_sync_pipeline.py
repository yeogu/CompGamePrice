import importlib.util
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
    def run_pipeline(self, accepted, collection_exit_code=0):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        database = root / "catalog.db"
        commands = []

        def synchronize(catalog, database_path, batch_size):
            with sqlite3.connect(database_path) as connection:
                pipeline.catalog_sync.initialize_state(connection)
            return {
                "status": "SUCCEEDED",
                "accepted": accepted,
                "acceptedAppIds": ["10"] if accepted else [],
            }

        def run(command, check, env):
            commands.append((command, check, env))
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

        def synchronize(catalog, database_path, batch_size):
            return {"status": "SUCCEEDED", "accepted": 0, "acceptedAppIds": []}

        commands = []

        def run(command, check, env):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0)

        retried, exit_code = pipeline.run_pipeline(
            ROOT,
            Path("catalog.json"),
            database,
            ROOT / "build/game_price_tracker",
            Path("snapshots"),
            20,
            synchronizer=synchronize,
            command_runner=run,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(retried["priceCollection"]["status"], "SUCCEEDED")
        self.assertEqual(len(commands), 1)


if __name__ == "__main__":
    unittest.main()
