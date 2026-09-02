from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_email_dispatcher


class EmailDispatcherTest(unittest.TestCase):
    def test_database_lock_waits_for_next_interval_without_crashing(self):
        with patch.object(
            run_email_dispatcher.dispatch_notification_outbox,
            "dispatch",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            result = run_email_dispatcher.dispatch_once(Path("prices.db"))
        self.assertEqual(result, (0, 0))

    def test_non_lock_database_error_is_not_hidden(self):
        with patch.object(
            run_email_dispatcher.dispatch_notification_outbox,
            "dispatch",
            side_effect=sqlite3.OperationalError("database is malformed"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                run_email_dispatcher.dispatch_once(Path("prices.db"))


if __name__ == "__main__":
    unittest.main()
