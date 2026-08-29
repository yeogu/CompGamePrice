import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "steam_catalog_sync",
    ROOT / "tools/sync_steam_catalog.py",
)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SteamCatalogSyncTest(unittest.TestCase):
    def setUp(self):
        self.detail = json.loads(
            (ROOT / "tests/fixtures/steam_appdetails_413150.json").read_text()
        )

    def app_list(self, apps):
        return json.dumps({"applist": {"apps": apps}}).encode()

    def detail_for(self, app_id, name=None, product_type="game"):
        payload = copy.deepcopy(self.detail)
        data = payload["413150"]["data"]
        data["steam_appid"] = int(app_id)
        data["name"] = name or f"Test Game {app_id}"
        data["type"] = product_type
        return json.dumps({app_id: {"success": True, "data": data}}).encode()

    def run_sync(self, apps, details, batch_size=20):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        catalog = root / "catalog.json"
        database = root / "catalog.db"
        catalog.write_text(
            json.dumps({"schemaVersion": 4, "games": []}),
            encoding="utf-8",
        )
        report = sync.synchronize(
            catalog,
            database,
            batch_size,
            app_list_fetcher=lambda: self.app_list(apps),
            detail_fetcher=lambda app_id: details[app_id],
        )
        return report, catalog, database

    def test_registers_only_bounded_batch_and_persists_progress(self):
        apps = [
            {"appid": 10, "name": "First Game"},
            {"appid": 20, "name": "Second Game"},
        ]
        details = {
            "10": self.detail_for("10", "First Game"),
            "20": self.detail_for("20", "Second Game"),
        }
        report, catalog, database = self.run_sync(apps, details, 1)
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["processed"], 1)
        self.assertEqual(json.loads(catalog.read_text())["games"][0]["id"], "first-game")
        with sqlite3.connect(database) as connection:
            state = connection.execute(
                "SELECT status, last_app_id, accepted_count FROM catalog_sync_state"
            ).fetchone()
        self.assertEqual(state, ("SUCCEEDED", "10", 1))

    def test_quarantines_localized_and_suspicious_titles(self):
        apps = [
            {"appid": 10, "name": "오구와 비밀의 숲"},
            {"appid": 20, "name": "Example Deluxe Edition"},
        ]
        details = {
            "10": self.detail_for("10", "오구와 비밀의 숲"),
            "20": self.detail_for("20", "Example Deluxe Edition"),
        }
        report, catalog, database = self.run_sync(apps, details)
        self.assertEqual(report["review"], 2)
        self.assertEqual(json.loads(catalog.read_text())["games"], [])
        with sqlite3.connect(database) as connection:
            reviews = connection.execute(
                "SELECT external_product_id, status FROM catalog_sync_review ORDER BY external_product_id"
            ).fetchall()
        self.assertEqual(reviews, [("10", "PENDING"), ("20", "PENDING")])
        status = sync.synchronization_status(database)
        self.assertEqual(status["status"], "SUCCEEDED")
        self.assertEqual(len(status["pendingReviews"]), 2)

    def test_skips_non_games_and_does_not_process_seen_apps_twice(self):
        apps = [{"appid": 10, "name": "Soundtrack"}]
        details = {"10": self.detail_for("10", "Soundtrack", "music")}
        report, catalog, database = self.run_sync(apps, details)
        self.assertEqual(report["skipped"], 1)
        second = sync.synchronize(
            catalog,
            database,
            20,
            app_list_fetcher=lambda: self.app_list(apps),
            detail_fetcher=lambda app_id: details[app_id],
        )
        self.assertEqual(second["processed"], 0)

    def test_rejects_invalid_batch_size_and_app_list(self):
        with self.assertRaisesRegex(ValueError, "batch size"):
            sync.synchronize(Path("unused"), Path("unused"), 0)
        with self.assertRaisesRegex(ValueError, "malformed"):
            sync.parse_app_list(b"not-json")

    def test_catalog_write_failure_does_not_mark_product_as_seen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            database = root / "catalog.db"
            catalog.write_text(
                json.dumps({"schemaVersion": 4, "games": []}),
                encoding="utf-8",
            )
            apps = [{"appid": 10, "name": "First Game"}]
            with mock.patch.object(
                sync.catalog_import,
                "write_catalog",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    sync.synchronize(
                        catalog,
                        database,
                        1,
                        app_list_fetcher=lambda: self.app_list(apps),
                        detail_fetcher=lambda app_id: self.detail_for(app_id, "First Game"),
                    )
            with sqlite3.connect(database) as connection:
                seen_count = connection.execute(
                    "SELECT COUNT(*) FROM catalog_sync_seen"
                ).fetchone()[0]
            self.assertEqual(seen_count, 0)
            self.assertEqual(sync.synchronization_status(database)["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
