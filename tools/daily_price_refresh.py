"""Refresh a frozen daily inventory, then retry only unavailable prices."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import signal
import subprocess
import sys
import tempfile
import time

from audit_catalog_price_integrity import store_key, parsed_time
from run_storefront_price_pipeline import COLLECTORS

KOREA = timezone(timedelta(hours=9))
STORES = {"Steam", "GooglePlay", "AppleAppStore", *COLLECTORS} - {"EpicGamesStore"}


def day_window():
    today = datetime.now(KOREA).replace(hour=0, minute=0, second=0, microsecond=0)
    return today.date().isoformat(), today.astimezone(timezone.utc)


def inventory(document):
    return {(p["store"], p["productId"]): {**p, "gameId": g["id"]}
            for g in document["games"] for p in g.get("products", [])
            if p["store"] in STORES and p.get("offerType", "BaseGame") in {"BaseGame", "Bundle"}}


def checks(database, targets=None):
    with sqlite3.connect(database, timeout=30) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(store_products)")}
        if not {"store", "external_product_id", "last_successful_check_at"} <= columns:
            return {}
        try:
            game_column = ",game_id" if "game_id" in columns else ""
            rows = connection.execute("SELECT store,external_product_id,last_successful_check_at" + game_column + " FROM store_products").fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            rows = []
    result = {}
    for row in rows:
        store, product, stamp = row[:3]
        key = store_key(store), str(product)
        if targets is not None and key in targets and len(row) > 3 and row[3] != targets[key]["gameId"]:
            continue
        checked = parsed_time(stamp)
        if checked is not None and checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        result[key] = checked
    return result


def initialize(database):
    with sqlite3.connect(database, timeout=30) as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS daily_price_targets(
                day TEXT, store TEXT, product_id TEXT, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
                PRIMARY KEY(day,store,product_id));
            CREATE TABLE IF NOT EXISTS daily_price_runs(
                day TEXT PRIMARY KEY, started_at REAL, finished_at REAL, status TEXT);
        """)


def coverage(document, database):
    day, midnight = day_window()
    targets = inventory(document)
    observed = checks(database, targets)
    confirmed = {key for key in targets if observed.get(key) and observed[key] >= midnight}
    failed = set()
    run = None
    with sqlite3.connect(database, timeout=30) as c:
        try:
            failed = {(s, p) for s, p in c.execute("SELECT store,product_id FROM daily_price_targets WHERE day=? AND status='FAILED'", (day,))}
            run = c.execute("SELECT started_at,finished_at,status FROM daily_price_runs WHERE day=?", (day,)).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
    failed = (failed & targets.keys()) - confirmed
    return {"day": day, "gameCount": len({p["gameId"] for p in targets.values()}), "target": len(targets), "confirmed": len(confirmed),
            "failed": len(failed), "pending": len(targets) - len(confirmed) - len(failed),
            "status": run[2] if run else "NOT_STARTED",
            "elapsedSeconds": round((run[1] or time.time()) - run[0]) if run else None,
            "stores": [{"store": store, "target": sum(k[0] == store for k in targets),
                        "confirmed": sum(k[0] == store for k in confirmed),
                        "failed": sum(k[0] == store for k in failed)}
                       for store in sorted({k[0] for k in targets})]}


def run_command(command, check=False, env=None, timeout=1200, stdout=None, stderr=None):
    del check
    process = subprocess.Popen(command, env=env, start_new_session=True, stdout=stdout, stderr=stderr)
    try:
        return subprocess.CompletedProcess(command, process.wait(timeout=timeout))
    except subprocess.TimeoutExpired:
        # Terminate import children too, before deleting their isolated snapshots.
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            process.wait()
        raise


def run_refresh(project, tracker, database, catalog, output, command_runner=run_command):
    document = json.loads(catalog.read_text())
    targets = inventory(document)
    batch_size = max(1, min(100, int(os.getenv("COLLECTION_PRICE_BATCH_SIZE", "40"))))
    workers = max(1, min(4, int(os.getenv("COLLECTION_STORE_WORKERS", "2"))))
    retry_delay = max(0, min(300, float(os.getenv("COLLECTION_RETRY_DELAY_SECONDS", "30"))))
    initialize(database)
    day, midnight = day_window()
    observed = checks(database, targets)
    with sqlite3.connect(database, timeout=30) as c:
        c.execute("INSERT INTO daily_price_runs VALUES(?,?,NULL,'RUNNING') ON CONFLICT(day) DO UPDATE SET started_at=excluded.started_at,finished_at=NULL,status='RUNNING'", (day, time.time()))
        for key in targets:
            status = "SUCCEEDED" if observed.get(key) and observed[key] >= midnight else "PENDING"
            c.execute("INSERT OR IGNORE INTO daily_price_targets(day,store,product_id,status) VALUES(?,?,?,?)", (day, *key, status))
            if status == "SUCCEEDED":
                c.execute("UPDATE daily_price_targets SET status='SUCCEEDED',error=NULL WHERE day=? AND store=? AND product_id=?", (day, *key))
        # Recover interrupted batches; never hold a transaction during network IO.
        c.execute("UPDATE daily_price_targets SET status='PENDING' WHERE day=? AND status='PROCESSING'", (day,))
    output.mkdir(parents=True, exist_ok=True)

    def process_store(store, selected):
        for offset in range(0, len(selected), batch_size):
            batch = selected[offset:offset + batch_size]
            ids = {key[1] for key in batch}
            with tempfile.TemporaryDirectory(prefix=f"daily-{store}-", dir=output) as directory:
                temporary = Path(directory)
                snapshot = temporary / "catalog.json"
                games = [{**g, "products": [p for p in g.get("products", []) if p["store"] == store and p["productId"] in ids]}
                         for g in document["games"]]
                snapshot.write_text(json.dumps({**document, "games": [g for g in games if g["products"]]}, ensure_ascii=False))
                if store == "Steam":
                    script, arguments = "run_steam_pipeline.py", ["--max-attempts", "1", "--request-delay", "0.5", "--skip-database-backup"]
                elif store in {"GooglePlay", "AppleAppStore"}:
                    script = "run_google_play_pipeline.py" if store == "GooglePlay" else "run_apple_pipeline.py"
                    arguments = []
                else:
                    script, arguments = "run_storefront_price_pipeline.py", ["--store", store]
                command = [sys.executable, str(project / "tools" / script), *arguments,
                           "--tracker", str(tracker), "--database", str(database),
                           "--catalog", str(snapshot), "--output-dir", str(temporary / "snapshots")]
                with sqlite3.connect(database, timeout=30) as c:
                    c.executemany("UPDATE daily_price_targets SET status='PROCESSING',attempts=attempts+1 WHERE day=? AND store=? AND product_id=?", [(day, *key) for key in batch])
                environment = {**os.environ, "GAME_PRICE_DATABASE_PATH": str(database),
                               "GAME_PRICE_CATALOG_PATH": str(snapshot), "STORE_COLLECTION_MAX_ATTEMPTS": "1",
                               "STEAM_COLLECTION_MAX_WORKERS": os.getenv("STEAM_COLLECTION_MAX_WORKERS", "2")}
                # Admin progress is job-local and must not be shared by store workers.
                environment.pop("GAME_PRICE_COLLECTION_PROGRESS_PATH", None)
                error = ""
                attempted_at = int(time.time())
                try:
                    result = command_runner(command, check=False, env=environment, timeout=1200)
                    if result.returncode:
                        error = f"수집/저장 실패 (exit {result.returncode})"
                except (OSError, subprocess.TimeoutExpired) as exception:
                    error = str(exception)
                observed_batch = checks(database, targets)
                details = {}
                steam_report = temporary / "snapshots" / "steam_pipeline_run.json"
                if store == "Steam" and steam_report.exists():
                    try:
                        details = {(store, row["appId"]): row["error"] for row in json.loads(steam_report.read_text()).get("failures", [])}
                    except (OSError, ValueError, KeyError):
                        pass
                with sqlite3.connect(database, timeout=30) as c:
                    try:
                        details.update({(s, p): message for s, p, message in c.execute("SELECT provider,external_product_id,error_message FROM catalog_product_collection_failures WHERE attempted_at >= datetime(?, 'unixepoch')", (attempted_at,))})
                    except sqlite3.OperationalError as exception:
                        if "no such table" not in str(exception): raise
                    for key in batch:
                        successful = observed_batch.get(key) and observed_batch[key] >= midnight
                        c.execute("UPDATE daily_price_targets SET status=?,error=? WHERE day=? AND store=? AND product_id=?",
                                  ("SUCCEEDED" if successful else "FAILED", None if successful else details.get(key, error or "정상 가격 확인 기록 없음"), day, *key))
                print(json.dumps({"dailyPrices": coverage(document, database)}, ensure_ascii=False), flush=True)

    # Complete the first pass for every store before spending time on retries.
    for pass_number in (0, 1):
        with sqlite3.connect(database, timeout=30) as c:
            rows = c.execute("SELECT store,product_id,status,attempts,error FROM daily_price_targets WHERE day=? AND status!='SUCCEEDED' AND attempts<2", (day,)).fetchall()
        grouped = {}
        for store, product, status, attempts, error in rows:
            key = store, product
            if key not in targets: continue
            if status == "FAILED" and any(marker in (error or "") for marker in ("HTTP 403", "HTTP 404", "REGION_MISMATCH")): continue
            if pass_number == 1 and status != "FAILED": continue
            grouped.setdefault(store, []).append(key)
        if pass_number == 1 and grouped and retry_delay:
            time.sleep(retry_delay)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {store: pool.submit(process_store, store, selected) for store, selected in grouped.items()}
            for store, future in futures.items():
                try:
                    future.result()
                except Exception as error:
                    # A store failure cannot prevent the remaining stores from running.
                    print(f"Daily {store} failed: {error}", file=sys.stderr, flush=True)
                    with sqlite3.connect(database, timeout=30) as c:
                        c.execute("UPDATE daily_price_targets SET status='FAILED',error=? WHERE day=? AND store=? AND status!='SUCCEEDED'", (str(error), day, store))
    summary = coverage(document, database)
    status = "SUCCEEDED" if summary["confirmed"] == summary["target"] else "PARTIAL_FAILURE"
    with sqlite3.connect(database, timeout=30) as c:
        c.execute("UPDATE daily_price_runs SET finished_at=?,status=? WHERE day=?", (time.time(), status, day))
    return [{"name": "daily-prices", "exitCode": 0 if status == "SUCCEEDED" else 2,
             "outcome": "SUCCEEDED" if status == "SUCCEEDED" else "PARTIAL", "coverage": coverage(document, database)}]
