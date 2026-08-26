#!/usr/bin/env python3
"""Generate a macOS launchd plist for the Steam collection pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
import plistlib
import sys


LABEL = "com.compgameprice.steam-collection"


def schedule_definition(project_directory: Path, hour: int, minute: int) -> dict:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Schedule time must be a valid hour and minute")

    project = project_directory.resolve()
    log_directory = project / "snapshots" / "logs"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            str(project / "tools" / "run_steam_pipeline.py"),
            "--tracker",
            str(project / "build" / "game_price_tracker"),
            "--targets",
            str(project / "data" / "steam_collection_targets.json"),
            "--catalog",
            str(project / "data" / "games.txt"),
            "--output-dir",
            str(project / "snapshots" / "latest"),
            "--archive-dir",
            str(project / "snapshots" / "archive"),
        ],
        "WorkingDirectory": str(project),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log_directory / "steam_pipeline.stdout.log"),
        "StandardErrorPath": str(log_directory / "steam_pipeline.stderr.log"),
        "ProcessType": "Background",
        "RunAtLoad": False,
    }


def write_schedule(
    project_directory: Path, output_path: Path, hour: int, minute: int
) -> None:
    definition = schedule_definition(project_directory, hour, minute)
    (project_directory / "snapshots" / "logs").mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output:
        plistlib.dump(definition, output, sort_keys=False)


def main() -> int:
    default_project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", default=default_project, type=Path)
    parser.add_argument(
        "--output",
        default=default_project / "snapshots" / f"{LABEL}.plist",
        type=Path,
    )
    parser.add_argument("--hour", default=9, type=int)
    parser.add_argument("--minute", default=0, type=int)
    arguments = parser.parse_args()

    try:
        write_schedule(
            arguments.project_dir,
            arguments.output,
            arguments.hour,
            arguments.minute,
        )
    except ValueError as error:
        parser.error(str(error))
    print(f"launchd schedule written to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
