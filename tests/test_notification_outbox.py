import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "notification_outbox", ROOT / "tools" / "dispatch_notification_outbox.py"
)
notification_outbox = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(notification_outbox)


class NotificationOutboxTest(unittest.TestCase):
    def test_delivers_pending_message_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "prices.db"
            output = root / "mail.jsonl"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT);
                    CREATE TABLE notifications(
                        id INTEGER PRIMARY KEY, user_id INTEGER, game_id TEXT,
                        store TEXT, price_minor INTEGER, currency TEXT, message TEXT
                    );
                    CREATE TABLE notification_outbox(
                        notification_id INTEGER PRIMARY KEY, channel TEXT, status TEXT
                    );
                    INSERT INTO users VALUES(1, 'buyer@example.com');
                    INSERT INTO notifications VALUES(
                        9, 1, 'hades', 'Steam', 15000, 'KRW', '목표가 도달'
                    );
                    INSERT INTO notification_outbox VALUES(9, 'email', 'PENDING');
                    """
                )
            self.assertEqual(
                notification_outbox.dispatch(database, output),
                (1, 0),
            )
            self.assertEqual(
                notification_outbox.dispatch(database, output),
                (0, 0),
            )
            message = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(message["to"], "buyer@example.com")
            with sqlite3.connect(database) as connection:
                status = connection.execute(
                    "SELECT status FROM notification_outbox WHERE notification_id = 9"
                ).fetchone()[0]
            self.assertEqual(status, "SENT")


if __name__ == "__main__":
    unittest.main()
