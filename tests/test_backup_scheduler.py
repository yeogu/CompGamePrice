import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_backup_scheduler


class BackupSchedulerTest(unittest.TestCase):
    def setUp(self):
        run_backup_scheduler.stop_requested = False

    def test_creates_verified_database_and_catalog_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "prices.db"
            catalog = root / "catalog.json"
            backups = root / "backups"
            status = root / "backup-status.json"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE prices(amount INTEGER)")
                connection.execute("INSERT INTO prices VALUES(16000)")
            catalog.write_text(
                json.dumps({"schemaVersion": 4, "games": []}),
                encoding="utf-8",
            )

            succeeded = run_backup_scheduler.run_backup(
                database,
                catalog,
                backups,
                14,
                status,
            )

            document = run_backup_scheduler.periodic_job_status.read_status(
                status,
                "backup",
            )
            self.assertTrue(succeeded)
            self.assertEqual(document["status"], "SUCCEEDED")
            self.assertTrue((backups / document["lastBackup"]).is_file())
            self.assertEqual(len(list(backups.glob("*.catalog.json"))), 1)

    def test_records_failure_without_deleting_previous_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backups = root / "backups"
            backups.mkdir()
            previous = backups / "previous.db"
            previous.write_bytes(b"existing")
            status = root / "backup-status.json"

            succeeded = run_backup_scheduler.run_backup(
                root / "missing.db",
                root / "missing-catalog.json",
                backups,
                14,
                status,
            )

            document = run_backup_scheduler.periodic_job_status.read_status(
                status,
                "backup",
            )
            self.assertFalse(succeeded)
            self.assertEqual(document["status"], "FAILED")
            self.assertTrue(previous.is_file())


if __name__ == "__main__":
    unittest.main()
