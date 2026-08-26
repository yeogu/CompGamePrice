import importlib.util
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "database_backup", ROOT / "tools" / "database_backup.py"
)
database_backup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(database_backup)


class DatabaseBackupTest(unittest.TestCase):
    def create_source(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE prices(game TEXT, amount INTEGER)")
            connection.execute("INSERT INTO prices VALUES('Stardew Valley', 16000)")

    def test_creates_verified_backup_and_restores_to_new_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            backup_directory = root / "backups"
            restored = root / "restored.db"
            self.create_source(source)
            now = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)

            backup, removed = database_backup.create_backup(
                source, backup_directory, 30, now
            )
            self.assertEqual(removed, 0)
            database_backup.verify_database(backup)
            metadata = json.loads(
                backup.with_suffix(".metadata.json").read_text()
            )
            self.assertEqual(metadata["integrityCheck"], "ok")
            self.assertEqual(len(metadata["sha256"]), 64)

            database_backup.restore_to_new_path(backup, restored)
            with sqlite3.connect(restored) as connection:
                row = connection.execute("SELECT game, amount FROM prices").fetchone()
            self.assertEqual(row, ("Stardew Valley", 16000))
            with self.assertRaises(FileExistsError):
                database_backup.restore_to_new_path(backup, restored)

    def test_rejects_corrupt_database(self):
        with tempfile.TemporaryDirectory() as directory:
            corrupt = Path(directory) / "corrupt.db"
            corrupt.write_bytes(b"not a sqlite database")
            with self.assertRaises((sqlite3.DatabaseError, RuntimeError)):
                database_backup.verify_database(corrupt)

    def test_prunes_only_expired_database_backup_files(self):
        with tempfile.TemporaryDirectory() as directory:
            backup_directory = Path(directory)
            old_database = backup_directory / "old.db"
            old_metadata = backup_directory / "old.metadata.json"
            recent_database = backup_directory / "recent.db"
            unrelated = backup_directory / "README.txt"
            for path in (old_database, old_metadata, recent_database, unrelated):
                path.write_text(path.name)
            old_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
            recent_timestamp = datetime(2026, 8, 20, tzinfo=timezone.utc).timestamp()
            for path in (old_database, old_metadata):
                os.utime(path, (old_timestamp, old_timestamp))
            os.utime(recent_database, (recent_timestamp, recent_timestamp))

            removed = database_backup.prune_backups(
                backup_directory,
                30,
                datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            self.assertEqual(removed, 2)
            self.assertFalse(old_database.exists())
            self.assertFalse(old_metadata.exists())
            self.assertTrue(recent_database.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
