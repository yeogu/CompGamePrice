from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import daily_price_refresh as refresh


class DailyPriceRefreshTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "prices.db"
        self.catalog = self.root / "catalog.json"
        self.environment = patch.dict(os.environ, {"COLLECTION_PRICE_BATCH_SIZE": "40", "COLLECTION_STORE_WORKERS": "2", "COLLECTION_RETRY_DELAY_SECONDS": "0"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        with sqlite3.connect(self.database) as c:
            c.execute("CREATE TABLE store_products(store TEXT, external_product_id TEXT, last_successful_check_at TEXT, PRIMARY KEY(store,external_product_id))")
        self.calls = []
        self.lock = threading.Lock()

    def document(self, count, extra=False):
        document = {"schemaVersion": 4, "games": [{"id": f"game-{n}", "title": f"Game {n}", "platforms": ["Windows"],
                    "products": [{"store": "Steam", "productId": str(n), "productUrl": f"https://store.steampowered.com/app/{n}", "offerType": "BaseGame"}]}
                   for n in range(count)]}
        if extra:
            document["games"][0]["products"].append({"store": "GooglePlay", "productId": "mobile", "offerType": "BaseGame", "productUrl": "https://play.google.com/store/apps/details?id=mobile"})
        self.catalog.write_text(json.dumps(document))
        return document

    def fake_runner(self, command, **kwargs):
        snapshot = json.loads(Path(command[command.index("--catalog") + 1]).read_text())
        targets = refresh.inventory(snapshot)
        with self.lock:
            self.calls.append(list(targets))
        self.confirm(targets)
        return SimpleNamespace(returncode=0)

    def confirm(self, targets):
        with sqlite3.connect(self.database, timeout=30) as c:
            for store, product in targets:
                c.execute("INSERT OR REPLACE INTO store_products VALUES(?,?,?)", (store, product, datetime.now(timezone.utc).isoformat()))

    def run_refresh(self, runner=None):
        return refresh.run_refresh(ROOT, ROOT / "build/game_price_tracker", self.database, self.catalog, self.root / "output", runner or self.fake_runner)

    def test_every_target_is_processed_not_just_one_batch(self):
        document = self.document(197)
        result = self.run_refresh()
        self.assertEqual(sorted(map(len, self.calls)), [37, 40, 40, 40, 40])
        self.assertEqual(result[0]["exitCode"], 0)
        self.assertEqual(refresh.coverage(document, self.database)["confirmed"], 197)
        self.run_refresh()
        self.assertEqual(len(self.calls), 5, "Today's confirmed prices must not be recollected")

    def test_retry_only_failed_products_after_other_stores(self):
        self.document(2, extra=True)
        attempts = []
        def runner(command, **kwargs):
            snapshot = json.loads(Path(command[command.index("--catalog") + 1]).read_text())
            targets = refresh.inventory(snapshot)
            with self.lock:
                attempts.append(list(targets))
                fail = sum(("Steam", "0") in batch for batch in attempts) == 1
            self.confirm(k for k in targets if not (fail and k == ("Steam", "0")))
            return SimpleNamespace(returncode=1 if fail else 0)
        self.assertEqual(self.run_refresh(runner)[0]["exitCode"], 0)
        self.assertEqual(attempts[-1], [("Steam", "0")])
        self.assertEqual(sum(("Steam", "1") in batch for batch in attempts), 1)
        self.assertTrue(any(("GooglePlay", "mobile") in batch for batch in attempts[:-1]))

    def test_success_exit_without_saved_prices_is_not_success(self):
        document = self.document(1)
        def runner(command, **kwargs):
            self.calls.append(command)
            return SimpleNamespace(returncode=0)
        result = self.run_refresh(runner)
        self.assertEqual(result[0]["exitCode"], 2)
        self.assertEqual(len(self.calls), 2)
        self.run_refresh(runner)
        self.assertEqual(len(self.calls), 2, "Failure attempts must be bounded per day")
        coverage = refresh.coverage(document, self.database)
        self.assertEqual((coverage["confirmed"], coverage["failed"], coverage["pending"]), (0, 1, 0))

    def test_store_failure_does_not_stop_other_stores(self):
        document = self.document(1, extra=True)
        def runner(command, **kwargs):
            if "run_steam_pipeline.py" in command[1]:
                raise OSError("unavailable")
            return self.fake_runner(command, **kwargs)
        result = self.run_refresh(runner)
        self.assertEqual(result[0]["exitCode"], 2)
        self.assertEqual(refresh.coverage(document, self.database)["confirmed"], 1)

    def test_stores_run_in_parallel_with_isolated_snapshots(self):
        self.document(1, extra=True)
        barrier = threading.Barrier(2)
        def runner(command, **kwargs):
            barrier.wait(timeout=3)
            return self.fake_runner(command, **kwargs)
        self.assertEqual(self.run_refresh(runner)[0]["exitCode"], 0)
        self.assertEqual(len(self.calls), 2)

    def test_new_registration_is_not_lost_on_same_day(self):
        self.document(1)
        self.run_refresh()
        self.document(2)
        self.run_refresh()
        self.assertEqual(self.calls[-1], [("Steam", "1")])

    def test_epic_and_demos_are_not_price_targets(self):
        document = self.document(1)
        document["games"][0]["products"] += [{"store": "EpicGamesStore", "productId": "epic", "offerType": "BaseGame"}, {"store": "Steam", "productId": "demo", "offerType": "Demo"}]
        self.assertEqual(list(refresh.inventory(document)), [("Steam", "0")])

    def test_korean_day_starts_at_utc_15_hours(self):
        day, midnight = refresh.day_window()
        self.assertEqual(midnight.hour, 15)
        self.assertEqual(midnight.astimezone(refresh.KOREA).date().isoformat(), day)

    def test_saved_response_reaches_real_cpp_storage(self):
        tracker = ROOT / "build/game_price_tracker"
        if not tracker.exists(): self.skipTest("Build tracker before the storage integration test")
        document = json.loads((ROOT / "data/game_catalog.json").read_text())
        game = document["games"][0]
        game["products"] = [p for p in game["products"] if p["store"] == "Steam"]
        document["games"] = [game]
        self.catalog.write_text(json.dumps(document))
        self.database = self.root / "real-storage.db"
        def runner(command, **kwargs):
            return subprocess.run([*command, "--input", str(ROOT / "tests/fixtures/steam_appdetails_413150.json")], **kwargs)
        result = self.run_refresh(runner)
        self.assertEqual(result[0]["exitCode"], 0)
        self.assertEqual(refresh.coverage(document, self.database)["confirmed"], 1)

    def test_wrong_canonical_game_is_not_confirmed(self):
        document = self.document(1)
        with sqlite3.connect(self.database) as c:
            c.execute("ALTER TABLE store_products ADD COLUMN game_id TEXT")
            c.execute("INSERT INTO store_products VALUES('Steam','0',?,'wrong-game')", (datetime.now(timezone.utc).isoformat(),))
        self.assertEqual(refresh.coverage(document, self.database)["confirmed"], 0)

    def test_404_is_not_retried_same_day(self):
        self.document(1)
        def runner(command, **kwargs):
            self.calls.append(command)
            with sqlite3.connect(self.database) as c:
                c.execute("CREATE TABLE IF NOT EXISTS catalog_product_collection_failures(provider TEXT,external_product_id TEXT,error_message TEXT,attempted_at TEXT)")
                c.execute("INSERT INTO catalog_product_collection_failures VALUES('Steam','0','Steam HTTP 404',datetime('now'))")
            return SimpleNamespace(returncode=1)
        self.run_refresh(runner)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
