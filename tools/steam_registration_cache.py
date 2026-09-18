"""Short-lived KRW responses from registration, reused only for initial prices."""

import sqlite3
import time

import collect_steam_snapshot as steam


def save(connection, app_id, game_id, raw, fetched_at=None):
    try:
        steam.normalized_row(raw, app_id, game_id)
    except (steam.SnapshotValidationError, ValueError, TypeError):
        return False
    connection.execute("""CREATE TABLE IF NOT EXISTS steam_registration_responses (
        app_id TEXT PRIMARY KEY, game_id TEXT NOT NULL, fetched_at REAL NOT NULL,
        response BLOB NOT NULL)""")
    connection.execute("DELETE FROM steam_registration_responses WHERE fetched_at < ?", (time.time() - 600,))
    connection.execute("INSERT OR REPLACE INTO steam_registration_responses VALUES (?, ?, ?, ?)",
                       (app_id, game_id, time.time() if fetched_at is None else fetched_at, raw))
    return True


def fetcher(database, fallback=steam.fetch):
    def cached_response(app_id, country):
        if country.lower() == "kr":
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30) as connection:
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='steam_registration_responses'").fetchone()
                row = connection.execute("SELECT game_id,response FROM steam_registration_responses WHERE app_id=? AND fetched_at>=?",
                                         (app_id, time.time() - 600)).fetchone() if exists else None
            if row:
                try:
                    steam.normalized_row(row[1], app_id, row[0])
                    return row[1], 200, f"registration-cache://steam/{app_id}"
                except (steam.SnapshotValidationError, ValueError, TypeError):
                    pass
        return None

    def fetch(app_id, country, language, timeout):
        cached = cached_response(app_id, country)
        if cached is not None:
            return cached
        return fallback(app_id, country, language, timeout)
    fetch.cached_response = cached_response
    return fetch
