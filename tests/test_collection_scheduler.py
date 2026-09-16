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
            {"name": "steam", "exitCode": 1, "outcome": "FAILED"},
            {"name": "google-play", "exitCode": 2, "outcome": "PARTIAL"},
            {"name": "collection-health", "exitCode": 1, "outcome": "WARNING"},
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
        self.assertEqual(summary["partialSteps"], ["google-play"])
        self.assertEqual(persisted["status"], "PARTIAL_FAILURE")
        self.assertEqual(persisted["failedSteps"], ["steam"])
        self.assertEqual(persisted["partialSteps"], ["google-play"])

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

    def test_busy_lock_retries_in_five_minutes_not_next_day(self):
        waits = []
        def wait(seconds, *args):
            waits.append(seconds)
            if len(waits) == 2: collection_scheduler.stop_requested = True
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "lock"
            with lock.open("w") as held, patch.object(collection_scheduler.periodic_job_status, "wait_with_heartbeat", side_effect=wait):
                collection_scheduler.fcntl.flock(held, collection_scheduler.fcntl.LOCK_EX | collection_scheduler.fcntl.LOCK_NB)
                collection_scheduler.run_scheduler(ROOT, Path("tracker"), Path(directory) / "db", Path(directory) / "output", lock, 86400, 0, 20, status_path=Path(directory) / "status.json")
        self.assertEqual(waits, [0, 300])

    def test_interval_is_anchored_to_cycle_start(self):
        waits = []
        def wait(seconds, *args):
            waits.append(seconds)
            if len(waits) == 2: collection_scheduler.stop_requested = True
        with tempfile.TemporaryDirectory() as directory, patch.object(collection_scheduler.periodic_job_status, "wait_with_heartbeat", side_effect=wait), patch.object(collection_scheduler, "run_once"), patch.object(collection_scheduler.time, "monotonic", side_effect=[0, 60]):
            collection_scheduler.run_scheduler(ROOT, Path("tracker"), Path(directory) / "db", Path(directory) / "output", Path(directory) / "lock", 86400, 0, 20, status_path=Path(directory) / "status.json")
        self.assertEqual(waits, [0, 86340])


if __name__ == "__main__":
    unittest.main()
