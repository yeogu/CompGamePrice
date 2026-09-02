import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "collection_scheduler", ROOT / "tools" / "run_collection_scheduler.py"
)
collection_scheduler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collection_scheduler)


class CollectionSchedulerTest(unittest.TestCase):
    def setUp(self):
        collection_scheduler.stop_requested = False

    def test_rejects_interval_that_would_overload_stores(self):
        with self.assertRaises(ValueError):
            collection_scheduler.periodic_job_status.parse_integer(
                "299",
                "interval",
                300,
            )

    def test_reports_partial_failure_without_raising(self):
        results = [
            {"name": "steam", "exitCode": 1},
            {"name": "google-play", "exitCode": 0},
        ]
        with patch.object(
            collection_scheduler.run_daily_operations,
            "run_operations",
            return_value=results,
        ):
            with tempfile.TemporaryDirectory() as directory:
                status = Path(directory) / "status.json"
                summary = collection_scheduler.run_once(
                    ROOT,
                    ROOT / "game_price_tracker",
                    ROOT / "game_prices.db",
                    ROOT / "snapshots/latest",
                    20,
                    status,
                )
                persisted = collection_scheduler.periodic_job_status.read_status(
                    status,
                    "collection",
                )
        self.assertEqual(summary["status"], "PARTIAL_FAILURE")
        self.assertEqual(summary["failedSteps"], ["steam"])
        self.assertEqual(persisted["status"], "PARTIAL_FAILURE")
        self.assertEqual(persisted["failedSteps"], ["steam"])

    def test_second_scheduler_cannot_use_same_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "scheduler.lock"
            with lock_path.open("w", encoding="utf-8") as lock_file:
                collection_scheduler.fcntl.flock(
                    lock_file,
                    collection_scheduler.fcntl.LOCK_EX | collection_scheduler.fcntl.LOCK_NB,
                )
                result = collection_scheduler.run_scheduler(
                    ROOT,
                    ROOT / "game_price_tracker",
                    ROOT / "game_prices.db",
                    Path(directory) / "output",
                    lock_path,
                    300,
                    0,
                    20,
                    True,
                )
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
