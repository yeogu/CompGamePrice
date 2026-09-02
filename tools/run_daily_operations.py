#!/usr/bin/env python3
"""Run independent collection, health, and notification jobs once."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def run_step(name: str, command: list[str], environment: dict[str, str]) -> dict:
    try:
        completed = subprocess.run(command, check=False, env=environment)
        return {"name": name, "exitCode": completed.returncode}
    except OSError as error:
        print(f"{name} could not start: {error}", file=sys.stderr)
        return {"name": name, "exitCode": 127, "error": str(error)}


def run_operations(
    project: Path,
    tracker: Path,
    database: Path,
    output_directory: Path,
    outbox_file: Path | None,
    catalog_batch_size: int = 20,
) -> list[dict]:
    python = sys.executable
    catalog = Path(
        os.environ.get(
            "GAME_PRICE_CATALOG_PATH",
            str(project / "data" / "game_catalog.json"),
        )
    )
    environment = os.environ.copy()
    environment["GAME_PRICE_DATABASE_PATH"] = str(database)
    environment["GAME_PRICE_CATALOG_PATH"] = str(catalog)
    steps = [
        (
            "steam-discovery",
            [
                python,
                str(project / "tools" / "discover_steam_catalog.py"),
                "--database",
                str(database),
                "--per-source-limit",
                "50",
                "--pages-per-source",
                "3",
            ],
        ),
        (
            "steam-catalog-sync",
            [
                python,
                str(project / "tools" / "sync_steam_catalog.py"),
                "--catalog",
                str(catalog),
                "--database",
                str(database),
                "--batch-size",
                str(catalog_batch_size),
            ],
        ),
        (
            "google-play-catalog-discovery",
            [
                python,
                str(project / "tools" / "sync_mobile_catalog.py"),
                "--store",
                "GooglePlay",
                "--catalog",
                str(catalog),
                "--database",
                str(database),
                "--batch-size",
                str(catalog_batch_size),
            ],
        ),
        (
            "apple-catalog-discovery",
            [
                python,
                str(project / "tools" / "sync_mobile_catalog.py"),
                "--store",
                "AppleAppStore",
                "--catalog",
                str(catalog),
                "--database",
                str(database),
                "--batch-size",
                str(catalog_batch_size),
            ],
        ),
        (
            "steam",
            [
                python,
                str(project / "tools" / "run_steam_pipeline.py"),
                "--tracker",
                str(tracker),
                "--catalog",
                str(catalog),
                "--output-dir",
                str(output_directory),
                "--database",
                str(database),
            ],
        ),
        (
            "google-play",
            [
                python,
                str(project / "tools" / "run_google_play_pipeline.py"),
                "--tracker",
                str(tracker),
                "--catalog",
                str(catalog),
                "--output-dir",
                str(output_directory),
                "--database",
                str(database),
            ],
        ),
        (
            "apple",
            [
                python,
                str(project / "tools" / "run_apple_pipeline.py"),
                "--tracker",
                str(tracker),
                "--catalog",
                str(catalog),
                "--output-dir",
                str(output_directory),
                "--database",
                str(database),
            ],
        ),
        (
            "collection-health",
            [
                python,
                str(project / "tools" / "check_collection_health.py"),
                "--database",
                str(database),
            ],
        ),
    ]
    if outbox_file is not None or (
        environment.get("SMTP_HOST") and environment.get("SMTP_FROM")
    ):
        outbox_command = [
            python,
            str(project / "tools" / "dispatch_notification_outbox.py"),
            "--database",
            str(database),
        ]
        if outbox_file is not None:
            outbox_command.extend(["--output-file", str(outbox_file)])
        steps.append(("notification-outbox", outbox_command))

    return [run_step(name, command, environment) for name, command in steps]


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", default=project / "build/game_price_tracker", type=Path)
    parser.add_argument("--database", default=project / "build/game_prices.db", type=Path)
    parser.add_argument("--output-dir", default=project / "snapshots/latest", type=Path)
    parser.add_argument("--outbox-file", type=Path)
    parser.add_argument("--catalog-batch-size", default=20, type=int)
    arguments = parser.parse_args()
    results = run_operations(
        project,
        arguments.tracker,
        arguments.database,
        arguments.output_dir,
        arguments.outbox_file,
        arguments.catalog_batch_size,
    )
    print(json.dumps({"steps": results}, ensure_ascii=False, indent=2))
    return 0 if all(step["exitCode"] == 0 for step in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
