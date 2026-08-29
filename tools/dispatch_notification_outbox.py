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


def pending_messages(connection: sqlite3.Connection, limit: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT o.notification_id, u.email, n.game_id, n.store,
               n.price_minor, n.currency, n.message
        FROM notification_outbox o
        JOIN notifications n ON n.id = o.notification_id
        JOIN users u ON u.id = n.user_id
        WHERE o.status = 'PENDING' AND o.channel = 'email'
        ORDER BY o.notification_id LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "notificationId": row[0],
            "to": row[1],
            "subject": f"[CompGamePrice] {row[2]} 가격 알림",
            "body": f"{row[2]} · {row[3]} · {row[4]} {row[5]}\n{row[6]}",
        }
        for row in rows
    ]


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
    with smtplib.SMTP(host, port, timeout=10) as client:
        client.starttls()
        username = os.environ.get("SMTP_USERNAME")
        password = os.environ.get("SMTP_PASSWORD")
        if username and password:
            client.login(username, password)
        client.send_message(email)


def dispatch(database: Path, output: Path | None, limit: int = 100) -> tuple[int, int]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    sent = 0
    failed = 0
    with sqlite3.connect(database) as connection:
        for message in pending_messages(connection, limit):
            try:
                if output is not None:
                    write_jsonl(message, output)
                else:
                    send_smtp(message)
                status = "SENT"
                sent += 1
            except Exception:
                status = "FAILED"
                failed += 1
            connection.execute(
                "UPDATE notification_outbox SET status = ? WHERE notification_id = ?",
                (status, message["notificationId"]),
            )
        connection.commit()
    return sent, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="build/game_prices.db", type=Path)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--limit", default=100, type=int)
    arguments = parser.parse_args()
    if arguments.output_file is None and not (
        os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM")
    ):
        parser.error("SMTP_HOST and SMTP_FROM are required without --output-file")
    sent, failed = dispatch(arguments.database, arguments.output_file, arguments.limit)
    print(json.dumps({"sent": sent, "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
