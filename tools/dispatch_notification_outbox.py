#!/usr/bin/env python3
"""Deliver pending notification emails from the SQLite outbox."""

from __future__ import annotations

import argparse
from email.message import EmailMessage
import json
import os
from pathlib import Path
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone


OUTBOX_COLUMNS = {
    "attempt_count": "INTEGER NOT NULL DEFAULT 0",
    "last_error": "TEXT",
    "last_attempt_at": "TEXT",
    "next_attempt_at": "TEXT",
    "sent_at": "TEXT",
}
DATABASE_BUSY_TIMEOUT_MILLISECONDS = 30000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def open_database(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        database,
        timeout=DATABASE_BUSY_TIMEOUT_MILLISECONDS / 1000,
    )
    connection.execute(
        f"PRAGMA busy_timeout={DATABASE_BUSY_TIMEOUT_MILLISECONDS}"
    )
    return connection


def ensure_delivery_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in connection.execute("PRAGMA table_info(notification_outbox)")
    }
    for name, definition in OUTBOX_COLUMNS.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE notification_outbox ADD COLUMN {name} {definition}"
            )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS email_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempt_at TEXT,
            next_attempt_at TEXT,
            sent_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def pending_messages(
    connection: sqlite3.Connection,
    limit: int,
    max_attempts: int,
    now: str,
) -> list[dict]:
    notification_rows = connection.execute(
        """
        SELECT o.notification_id, u.email, n.game_id, n.store,
               n.price_minor, n.currency, n.message, o.attempt_count
        FROM notification_outbox o
        JOIN notifications n ON n.id = o.notification_id
        JOIN users u ON u.id = n.user_id
        WHERE o.status IN ('PENDING', 'FAILED')
          AND o.channel = 'email'
          AND o.attempt_count < ?
          AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= ?)
        ORDER BY o.notification_id LIMIT ?
        """,
        (max_attempts, now, limit),
    ).fetchall()
    messages = [
        {
            "outboxType": "notification",
            "outboxId": row[0],
            "notificationId": row[0],
            "to": row[1],
            "subject": f"[DealQuest] {row[2]} 가격 알림",
            "body": f"{row[2]} · {row[3]} · {row[4]} {row[5]}\n{row[6]}",
            "attemptCount": row[7],
        }
        for row in notification_rows
    ]
    email_rows = connection.execute(
        """
        SELECT id, recipient, subject, body, attempt_count
        FROM email_outbox
        WHERE status IN ('PENDING', 'FAILED')
          AND attempt_count < ?
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY id LIMIT ?
        """,
        (max_attempts, now, limit),
    ).fetchall()
    messages.extend(
        {
            "outboxType": "email",
            "outboxId": row[0],
            "to": row[1],
            "subject": row[2],
            "body": row[3],
            "attemptCount": row[4],
        }
        for row in email_rows
    )
    return messages[:limit]


def write_jsonl(message: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(message, ensure_ascii=False) + "\n")


def send_smtp(message: dict) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ["SMTP_FROM"]
    email = EmailMessage()
    email["From"] = sender
    email["To"] = message["to"]
    email["Subject"] = message["subject"]
    email.set_content(message["body"])
    use_ssl = os.environ.get("SMTP_SSL", "false").casefold() == "true"
    client_type = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with client_type(host, port, timeout=10) as client:
        if not use_ssl and os.environ.get("SMTP_STARTTLS", "true").casefold() != "false":
            client.starttls()
        username = os.environ.get("SMTP_USERNAME")
        password = os.environ.get("SMTP_PASSWORD")
        if username and password:
            client.login(username, password)
        client.send_message(email)


def dispatch(
    database: Path,
    output: Path | None,
    limit: int = 100,
    max_attempts: int = 3,
    retry_base_seconds: int = 60,
) -> tuple[int, int]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_base_seconds < 0:
        raise ValueError("retry_base_seconds cannot be negative")
    sent = 0
    failed = 0
    with open_database(database) as connection:
        ensure_delivery_columns(connection)
        connection.commit()
        current_time = utc_now()
        current_timestamp = timestamp(current_time)
        for message in pending_messages(
            connection,
            limit,
            max_attempts,
            current_timestamp,
        ):
            error_message = None
            sent_at = None
            next_attempt_at = None
            try:
                if output is not None:
                    write_jsonl(message, output)
                else:
                    send_smtp(message)
                status = "SENT"
                sent += 1
                sent_at = current_timestamp
            except Exception as error:
                status = "FAILED"
                failed += 1
                error_message = str(error)[:1000]
                delay = retry_base_seconds * (2 ** message["attemptCount"])
                next_attempt_at = timestamp(
                    current_time + timedelta(seconds=delay)
                )
            table = (
                "notification_outbox"
                if message["outboxType"] == "notification"
                else "email_outbox"
            )
            id_column = (
                "notification_id"
                if message["outboxType"] == "notification"
                else "id"
            )
            connection.execute(
                f"""
                UPDATE {table}
                SET status = ?, attempt_count = attempt_count + 1,
                    last_error = ?, last_attempt_at = ?,
                    next_attempt_at = ?, sent_at = ?
                WHERE {id_column} = ?
                """,
                (
                    status,
                    error_message,
                    current_timestamp,
                    next_attempt_at,
                    sent_at,
                    message["outboxId"],
                ),
            )
            if message["outboxType"] == "email" and status == "SENT":
                connection.execute(
                    "UPDATE email_outbox SET body='[delivered]' WHERE id=?",
                    (message["outboxId"],),
                )
        connection.commit()
    return sent, failed


def delivery_status(database: Path, max_attempts: int = 3) -> dict:
    with open_database(database) as connection:
        ensure_delivery_columns(connection)
        connection.commit()
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'FAILED' AND attempt_count < ? THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'FAILED' AND attempt_count >= ? THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'SENT' THEN 1 ELSE 0 END)
            FROM notification_outbox
            """,
            (max_attempts, max_attempts),
        ).fetchone()
    return {
        "pending": row[0] or 0,
        "retryable": row[1] or 0,
        "exhausted": row[2] or 0,
        "sent": row[3] or 0,
    }


def email_delivery_status(database: Path, max_attempts: int = 3) -> dict:
    with open_database(database) as connection:
        ensure_delivery_columns(connection)
        connection.commit()
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'FAILED' AND attempt_count < ? THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'FAILED' AND attempt_count >= ? THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'SENT' THEN 1 ELSE 0 END)
            FROM email_outbox
            """,
            (max_attempts, max_attempts),
        ).fetchone()
        last_failure = connection.execute(
            """
            SELECT last_error, last_attempt_at
            FROM email_outbox
            WHERE status = 'FAILED'
            ORDER BY COALESCE(last_attempt_at, created_at) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "pending": row[0] or 0,
        "retryable": row[1] or 0,
        "exhausted": row[2] or 0,
        "sent": row[3] or 0,
        "lastError": None if last_failure is None else last_failure[0],
        "lastAttemptAt": None if last_failure is None else last_failure[1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="build/game_prices.db", type=Path)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--limit", default=100, type=int)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-base-seconds", default=60, type=int)
    parser.add_argument("--status", action="store_true")
    arguments = parser.parse_args()
    if arguments.status:
        print(json.dumps(delivery_status(arguments.database, arguments.max_attempts)))
        return 0
    if arguments.output_file is None and not (
        os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM")
    ):
        parser.error("SMTP_HOST and SMTP_FROM are required without --output-file")
    sent, failed = dispatch(
        arguments.database,
        arguments.output_file,
        arguments.limit,
        arguments.max_attempts,
        arguments.retry_base_seconds,
    )
    print(json.dumps({"sent": sent, "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
