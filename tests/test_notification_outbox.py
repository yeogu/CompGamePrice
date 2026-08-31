import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


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
                delivery = connection.execute(
                    """
                    SELECT status, attempt_count, last_error, sent_at
                    FROM notification_outbox
                    WHERE notification_id = 9
                    """
                ).fetchone()
            self.assertEqual(delivery[0], "SENT")
            self.assertEqual(delivery[1], 1)
            self.assertIsNone(delivery[2])
            self.assertIsNotNone(delivery[3])

    def test_retries_with_a_bound_and_records_failure_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "prices.db"
            self.create_pending_message(database)
            with patch.object(
                notification_outbox,
                "send_smtp",
                side_effect=OSError("mail server unavailable"),
            ) as sender:
                for _ in range(4):
                    notification_outbox.dispatch(
                        database,
                        None,
                        max_attempts=3,
                        retry_base_seconds=0,
                    )
            self.assertEqual(sender.call_count, 3)
            with sqlite3.connect(database) as connection:
                delivery = connection.execute(
                    """
                    SELECT status, attempt_count, last_error, last_attempt_at
                    FROM notification_outbox
                    WHERE notification_id = 9
                    """
                ).fetchone()
            self.assertEqual(delivery[0], "FAILED")
            self.assertEqual(delivery[1], 3)
            self.assertEqual(delivery[2], "mail server unavailable")
            self.assertIsNotNone(delivery[3])
            self.assertEqual(
                notification_outbox.delivery_status(database),
                {
                    "pending": 0,
                    "retryable": 0,
                    "exhausted": 1,
                    "sent": 0,
                },
            )

    def test_failed_delivery_can_succeed_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "prices.db"
            output = root / "mail.jsonl"
            self.create_pending_message(database)
            with patch.object(
                notification_outbox,
                "send_smtp",
                side_effect=OSError("temporary failure"),
            ):
                self.assertEqual(
                    notification_outbox.dispatch(
                        database,
                        None,
                        retry_base_seconds=0,
                    ),
                    (0, 1),
                )
            self.assertEqual(
                notification_outbox.dispatch(
                    database,
                    output,
                    retry_base_seconds=0,
                ),
                (1, 0),
            )
            with sqlite3.connect(database) as connection:
                delivery = connection.execute(
                    """
                    SELECT status, attempt_count, last_error
                    FROM notification_outbox
                    WHERE notification_id = 9
                    """
                ).fetchone()
            self.assertEqual(delivery, ("SENT", 2, None))

    def create_pending_message(self, database: Path) -> None:
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT);
                CREATE TABLE notifications(
                    id INTEGER PRIMARY KEY, user_id INTEGER, game_id TEXT,
                    store TEXT, price_minor INTEGER, currency TEXT, message TEXT
                );
                CREATE TABLE notification_outbox(
                    notification_id INTEGER PRIMARY KEY,
                    channel TEXT,
                    status TEXT
                );
                INSERT INTO users VALUES(1, 'buyer@example.com');
                INSERT INTO notifications VALUES(
                    9, 1, 'hades', 'Steam', 15000, 'KRW', '목표가 도달'
                );
                INSERT INTO notification_outbox VALUES(9, 'email', 'PENDING');
                """
            )


if __name__ == "__main__":
    unittest.main()
