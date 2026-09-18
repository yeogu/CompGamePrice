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

    def test_full_catalog_batch_continues_after_five_seconds(self):
        waits = []
        def wait(seconds, *args):
            waits.append(seconds)
            if len(waits) == 2: collection_scheduler.stop_requested = True
        summary = {"steps": [{"name": "steam-registration-1", "report": {
            "status": "SUCCEEDED", "processed": 100, "failed": 0}}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(collection_scheduler.periodic_job_status, "wait_with_heartbeat", side_effect=wait), patch.object(collection_scheduler, "run_once", return_value=summary):
            root = Path(directory)
            collection_scheduler.run_scheduler(ROOT, root / "tracker", root / "db", root / "out", root / "lock", 3600, 0, 100, status_path=root / "status", mode="catalog")
        self.assertEqual(waits, [0, 5])
        summary["steps"][0]["report"]["failed"] = 1
        self.assertFalse(collection_scheduler.catalog_has_more_work(summary, 100))

    def test_due_price_reservation_blocks_catalog_even_when_main_lock_is_free(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collection_scheduler, "run_once") as run:
            root = Path(directory)
            with (root / "lock.prices").open("a+") as reservation:
                collection_scheduler.fcntl.flock(reservation, collection_scheduler.fcntl.LOCK_EX)
                result = collection_scheduler.run_scheduler(ROOT, root / "tracker", root / "db", root / "out", root / "lock", 3600, 0, 100, single_run=True, status_path=root / "status", mode="catalog")
            self.assertEqual(result, 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
