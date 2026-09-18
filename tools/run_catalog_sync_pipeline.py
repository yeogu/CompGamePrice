#!/usr/bin/env python3
"""Discover Steam catalog games and collect prices for newly registered games."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import time

import sync_steam_catalog as catalog_sync
from daily_price_refresh import checks, inventory, run_command


def run_initial_price_command(command, check=False, env=None):
    output = Path(command[command.index("--output-dir") + 1]).parent
    with (output / "initial-prices.stdout.log").open("w") as stdout, (output / "initial-prices.stderr.log").open("w") as stderr:
        return run_command(command, check=check, env=env, stdout=stdout, stderr=stderr)


def collect_registered_prices(project, catalog, database, tracker, output_directory,
                              app_ids, command_runner=run_initial_price_command, limit=100):
    """Persist a small retry queue; never re-fetch the entire catalog after registration."""
    with sqlite3.connect(database, timeout=30) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS catalog_initial_prices (
            app_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, next_attempt_at REAL NOT NULL DEFAULT 0)""")
        if "next_attempt_at" not in {row[1] for row in connection.execute("PRAGMA table_info(catalog_initial_prices)")}:
            connection.execute("ALTER TABLE catalog_initial_prices ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0")
        connection.executemany("INSERT OR IGNORE INTO catalog_initial_prices(app_id,created_at) VALUES (?, ?)",
                               [(app_id, catalog_sync.utc_now()) for app_id in app_ids])
        waiting = dict(connection.execute(
            "SELECT app_id,next_attempt_at FROM catalog_initial_prices ORDER BY created_at, app_id"))
    if not waiting:
        catalog_sync.record_price_collection(database, "NOT_REQUIRED", None)
        return {"status": "NOT_REQUIRED", "exitCode": None, "targets": 0}, 0
    document = json.loads(catalog.read_text(encoding="utf-8"))
    available = catalog_sync.existing_steam_ids(document)
    targets = inventory(document)
    observed = checks(database, targets)
    confirmed = {app_id for app_id in available if observed.get(("Steam", app_id))}
    removed = (set(waiting) - available) | (set(waiting) & confirmed)
    with sqlite3.connect(database, timeout=30) as connection:
        connection.executemany("DELETE FROM catalog_initial_prices WHERE app_id = ?",
                               [(app_id,) for app_id in removed])
    # Newly registered games get their first price even if earlier failures are queued.
    eligible = available - removed
    selected = set([app_id for app_id in dict.fromkeys([*app_ids, *waiting])
                    if app_id in eligible and waiting.get(app_id, 0) <= time.time()][:limit])
    if not selected:
        catalog_sync.record_price_collection(database, "NOT_REQUIRED", None)
        return {"status": "NOT_REQUIRED", "exitCode": None, "targets": 0}, 0
    output_directory.mkdir(parents=True, exist_ok=True)
    catalog_sync.record_price_collection(database, "RUNNING", None)
    # Rotate failures away from the head, including if the process is interrupted.
    # Daily refresh also retries these products according to its own daily budget.
    with sqlite3.connect(database, timeout=30) as connection:
        connection.executemany("UPDATE catalog_initial_prices SET next_attempt_at=? WHERE app_id=?",
                               [(time.time() + 86400, app_id) for app_id in selected])
    try:
        with tempfile.TemporaryDirectory(prefix="new-game-prices-", dir=output_directory) as directory:
            temporary = Path(directory)
            snapshot = temporary / "catalog.json"
            games = [{**game, "products": [product for product in game.get("products", [])
                       if product.get("store") == "Steam" and product.get("productId") in selected]}
                     for game in document["games"]]
            snapshot.write_text(json.dumps({**document, "games": [game for game in games if game["products"]]}, ensure_ascii=False), encoding="utf-8")
            completed = command_runner([
                sys.executable, str(project / "tools/run_steam_pipeline.py"),
                "--tracker", str(tracker), "--catalog", str(snapshot),
                "--output-dir", str(temporary), "--database", str(database), "--max-attempts", "1",
                "--registration-cache", str(database),
                "--skip-database-backup",
            ], check=False, env={**os.environ, "GAME_PRICE_DATABASE_PATH": str(database),
                                 "GAME_PRICE_CATALOG_PATH": str(snapshot)})
        code = completed.returncode
        error = None if code == 0 else "New game price collection incomplete; queued for retry"
    except (OSError, subprocess.TimeoutExpired) as exception:
        code, error = 1, str(exception)
    observed = checks(database, targets)
    confirmed = {app_id for app_id in selected if observed.get(("Steam", app_id))}
    with sqlite3.connect(database, timeout=30) as connection:
        connection.executemany("DELETE FROM catalog_initial_prices WHERE app_id = ?",
                               [(app_id,) for app_id in confirmed])
    if confirmed == selected:
        code, error = 0, None
    elif confirmed:
        code = 2
    else:
        code = 1
    if code and not error:
        error = "Price rows were not saved for all new games; queued for retry"
    status = "SUCCEEDED" if code == 0 else "PARTIAL" if code == 2 else "FAILED"
    catalog_sync.record_price_collection(database, status, code, error)
    return {"status": status, "exitCode": code, "error": error, "targets": len(selected),
            "confirmed": len(confirmed)}, code


def run_pipeline(
    project: Path,
    catalog: Path,
    database: Path,
    tracker: Path,
    output_directory: Path,
    batch_size: int,
    synchronizer=catalog_sync.synchronize,
    command_runner=run_initial_price_command,
) -> tuple[dict, int]:
    report = synchronizer(catalog, database, batch_size)
    price_started = time.monotonic()
    report["priceCollection"], price_code = collect_registered_prices(
        project, catalog, database, tracker, output_directory,
        report.get("acceptedAppIds", []), command_runner,
    )
    report["initialPriceSeconds"] = round(time.monotonic() - price_started, 3)
    sync_code = 1 if report["status"] == "FAILED" else 2 if report.get("failed", 0) else 0
    code = 1 if 1 in (sync_code, price_code) else max(sync_code, price_code)
    return report, code


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=project / "data/game_catalog.json", type=Path)
    parser.add_argument("--database", default=project / "build/game_prices.db", type=Path)
    parser.add_argument("--tracker", default=project / "build/game_price_tracker", type=Path)
    parser.add_argument("--output-dir", default=project / "snapshots/latest", type=Path)
    parser.add_argument("--batch-size", default=20, type=int)
    arguments = parser.parse_args()
    try:
        report, exit_code = run_pipeline(
            project,
            arguments.catalog,
            arguments.database,
            arguments.tracker,
            arguments.output_dir,
            arguments.batch_size,
        )
    except Exception as error:
        print(f"Catalog synchronization pipeline failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
