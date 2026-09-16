import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from collection_progress import ProgressReporter
import storefront_price_support as support


class CollectionProgressTest(unittest.TestCase):
    def test_parallel_completion_counts_are_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "progress.json"
            with patch.dict(os.environ, {"GAME_PRICE_COLLECTION_PROGRESS_PATH": str(destination)}):
                reporter = ProgressReporter(100)
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(reporter.completed, [True, False] * 50))
                self.assertEqual(json.loads(destination.read_text()), {
                    "total": 100, "processed": 100, "succeeded": 50, "failed": 50,
                })

    def test_updates_before_next_product_and_counts_retries_once(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "progress.json"
            calls = []
            def fetch(product, game, url, timeout):
                calls.append(product)
                if product == "second":
                    self.assertEqual(json.loads(destination.read_text())["processed"], 1)
                    raise TimeoutError("timeout")
                return b"ok"
            with patch.dict(os.environ, {"GAME_PRICE_COLLECTION_PROGRESS_PATH": str(destination)}):
                rows, failures = support.collect_with_retry(
                    [("first", "game", "url"), ("second", "game", "url")],
                    lambda *args: "row", fetch, 1, 2, 0, 0, max_workers=1,
                )
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(calls, ["first", "second", "second"])
            self.assertEqual(json.loads(destination.read_text()), {
                "total": 2, "processed": 2, "succeeded": 1, "failed": 1,
            })

    def test_no_progress_path_performs_no_file_io(self):
        with patch.dict(os.environ, {}, clear=True), patch("collection_progress.tempfile.NamedTemporaryFile") as output:
            reporter = ProgressReporter(0)
            reporter.completed(True)
            output.assert_not_called()

    def test_reporting_error_does_not_fail_collection(self):
        with patch.dict(os.environ, {"GAME_PRICE_COLLECTION_PROGRESS_PATH": "/does-not-exist/progress.json"}):
            reporter = ProgressReporter(1)
            reporter.completed(True)
            self.assertEqual(reporter.state["processed"], 1)


if __name__ == "__main__":
    unittest.main()
