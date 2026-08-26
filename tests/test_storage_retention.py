import importlib.util
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "storage_retention", ROOT / "tools" / "storage_retention.py"
)
storage_retention = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(storage_retention)


class StorageRetentionTest(unittest.TestCase):
    def test_removes_only_expired_archive_files(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive"
            app = archive / "413150"
            app.mkdir(parents=True)
            old_raw = app / "old.json.gz"
            old_metadata = app / "old.metadata.json"
            recent_raw = app / "recent.json.gz"
            unrelated = app / "notes.txt"
            for path in (old_raw, old_metadata, recent_raw, unrelated):
                path.write_text(path.name)

            now = datetime(2026, 8, 26, tzinfo=timezone.utc)
            old_timestamp = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
            recent_timestamp = datetime(2026, 8, 20, tzinfo=timezone.utc).timestamp()
            os.utime(old_raw, (old_timestamp, old_timestamp))
            os.utime(old_metadata, (old_timestamp, old_timestamp))
            os.utime(recent_raw, (recent_timestamp, recent_timestamp))

            removed = storage_retention.prune_archive(archive, 90, now)
            self.assertEqual(removed, 2)
            self.assertFalse(old_raw.exists())
            self.assertFalse(old_metadata.exists())
            self.assertTrue(recent_raw.exists())
            self.assertTrue(unrelated.exists())

    def test_trims_large_log_and_preserves_recent_complete_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "collector.log"
            log.write_bytes(b"old-line\n" * 20 + b"recent-one\nrecent-two\n")
            trimmed = storage_retention.trim_log(log, max_bytes=100, keep_bytes=40)
            self.assertTrue(trimmed)
            content = log.read_text()
            self.assertTrue(content.endswith("recent-one\nrecent-two\n"))
            self.assertLessEqual(log.stat().st_size, 40)

    def test_keeps_small_log_unchanged_and_validates_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "collector.log"
            log.write_text("small\n")
            self.assertFalse(storage_retention.trim_log(log, 100, 50))
            self.assertEqual(log.read_text(), "small\n")
        with self.assertRaises(ValueError):
            storage_retention.trim_log(Path("unused"), 100, 100)
        with self.assertRaises(ValueError):
            storage_retention.prune_archive(Path("unused"), 0)


if __name__ == "__main__":
    unittest.main()
