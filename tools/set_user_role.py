#!/usr/bin/env python3
"""Assign USER or ADMIN role to an existing account."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


def set_user_role(database: Path, email: str, role: str) -> dict:
    normalized_email = email.strip().casefold()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("valid user email is required")
    if role not in {"USER", "ADMIN"}:
        raise ValueError("role must be USER or ADMIN")
    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(users)")
        }
        if "role" not in columns:
            raise ValueError("database schema must be migrated by starting the application")
        cursor = connection.execute(
            "UPDATE users SET role = ? WHERE email = ? COLLATE NOCASE",
            (role, normalized_email),
        )
        if cursor.rowcount != 1:
            raise ValueError("user account was not found")
        connection.commit()
    return {"email": normalized_email, "role": role}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=root / "build/game_prices.db", type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", default="ADMIN", choices=("USER", "ADMIN"))
    arguments = parser.parse_args()
    try:
        result = set_user_role(arguments.database, arguments.email, arguments.role)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
