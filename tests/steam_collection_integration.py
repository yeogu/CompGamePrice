#!/usr/bin/env python3
"""End-to-end test for Steam fixture collection and SQLite import."""

from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile


def run(command: list[str], environment: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        command,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def scalar(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError(f"Query returned no row: {query}")
    return int(row[0])


def main() -> int:
    if len(sys.argv) != 6:
        raise RuntimeError(
            "Expected: tracker python pipeline fixture targets"
        )
    tracker, python, pipeline, fixture, targets = sys.argv[1:]

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        snapshot = root / "snapshot"
        database = root / "game_prices.db"
        environment = os.environ.copy()
        environment["GAME_PRICE_DATABASE_PATH"] = str(database)

        pipeline_command = [
            python,
            pipeline,
            "--tracker",
            tracker,
            "--targets",
            targets,
            "--input",
            fixture,
            "--output-dir",
            str(snapshot),
            "--request-delay",
            "0",
            "--retry-delay",
            "0",
        ]
        run(pipeline_command, environment)
        run(pipeline_command, environment)

        with sqlite3.connect(database) as connection:
            if scalar(connection, "SELECT COUNT(*) FROM store_products") != 1:
                raise RuntimeError("Expected one normalized Steam product")
            if scalar(connection, "SELECT price_minor FROM store_products") != 16000:
                raise RuntimeError("Expected normalized Steam price of 16000 KRW")
            if scalar(connection, "SELECT COUNT(*) FROM price_history") != 1:
                raise RuntimeError("Unchanged collection must not duplicate price history")
            if scalar(connection, "SELECT COUNT(*) FROM crawl_runs") != 2:
                raise RuntimeError("Each successful import should record one crawl run")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
