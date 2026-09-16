"""Bounded, resumable catalog growth, independent of metadata maintenance."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import discover_steam_catalog
import run_catalog_sync_pipeline


def pending_count(database: Path) -> int:
    if not database.exists():
        return 0
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_discovery_candidates'").fetchone():
            return 0
        return connection.execute("SELECT COUNT(*) FROM catalog_discovery_candidates WHERE provider='Steam' AND status='PENDING'").fetchone()[0]


def run_growth(project, tracker, database, catalog, output, batch_size=100,
               per_source_limit=100, pages_per_source=2, *, max_batches=None,
               discoverer=None, pipeline_runner=None):
    max_batches = int(os.getenv("CATALOG_INGEST_MAX_BATCHES", "2")) if max_batches is None else max_batches
    if not 1 <= batch_size <= 100 or not 1 <= max_batches <= 10:
        raise ValueError("catalog batch size must be 1..100; max batches must be 1..10")
    discoverer = discoverer or discover_steam_catalog.run_discovery
    pipeline_runner = pipeline_runner or run_catalog_sync_pipeline.run_pipeline
    results = []
    # Let registration catch up rather than endlessly expanding the same queue.
    pending = pending_count(database)
    if pending < max(1000, batch_size * max_batches):
        try:
            discovery = discoverer(database, per_source_limit=per_source_limit,
                                   pages_per_source=pages_per_source)
            status = discovery.get("status", "FAILED")
            results.append({"name": "steam-discovery", "exitCode": 1 if status == "FAILED" else 2 if status == "PARTIAL" else 0,
                            "outcome": "FAILED" if status == "FAILED" else "PARTIAL" if status == "PARTIAL" else "SUCCEEDED",
                            "report": discovery})
        except Exception as error:
            results.append({"name": "steam-discovery", "exitCode": 1, "outcome": "FAILED", "error": str(error)})
    else:
        results.append({"name": "steam-discovery", "exitCode": 0, "outcome": "SUCCEEDED",
                        "report": {"status": "BACKLOG", "pending": pending, "queued": 0}})
    # Discovery can fail while previously queued, verified candidates remain useful.
    for index in range(max_batches):
        try:
            report, code = pipeline_runner(project, catalog, database, tracker, output, batch_size)
            results.append({"name": f"steam-registration-{index + 1}", "exitCode": code,
                            "outcome": "SUCCEEDED" if code == 0 else "PARTIAL" if code == 2 else "FAILED",
                            "report": report})
            # Empty queue, exhausted current batch, or provider failure: wait for next cycle.
            if report.get("processed", 0) < batch_size or report.get("failed", 0) or report.get("status") == "FAILED":
                break
        except Exception as error:
            results.append({"name": f"steam-registration-{index + 1}", "exitCode": 1,
                            "outcome": "FAILED", "error": str(error)})
            break
    print(json.dumps({"catalogGrowth": results}, ensure_ascii=False), flush=True)
    return results
