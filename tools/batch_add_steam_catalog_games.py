#!/usr/bin/env python3
"""Preview or atomically add a list of verified Steam games to the catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import add_steam_catalog_game as catalog_import
import collect_steam_snapshot as steam


def load_targets(path: Path) -> list[tuple[str, str | None]]:
    targets = []
    seen = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        value = raw_line.split("#", 1)[0].strip()
        if not value:
            continue
        fields = [field.strip() for field in value.split(",")]
        if len(fields) > 2 or not fields[0].isdigit():
            raise ValueError(
                f"Line {line_number} must contain app_id or app_id,game-id"
            )
        app_id = fields[0]
        game_id = fields[1] if len(fields) == 2 and fields[1] else None
        if app_id in seen:
            raise ValueError(f"Duplicate Steam app id in input: {app_id}")
        seen.add(app_id)
        targets.append((app_id, game_id))
    if not targets:
        raise ValueError("Steam app id list is empty")
    return targets


def prepare_batch(
    catalog: dict,
    targets: list[tuple[str, str | None]],
    fetcher,
    request_delay: float,
) -> tuple[dict, list[dict], list[dict]]:
    if request_delay < 0:
        raise ValueError("request delay must be non-negative")
    updated = catalog
    accepted = []
    rejected = []
    for index, (app_id, game_id) in enumerate(targets):
        if index > 0 and request_delay > 0:
            time.sleep(request_delay)
        try:
            raw = fetcher(app_id)
            game = catalog_import.catalog_game(raw, app_id, game_id)
            updated = catalog_import.updated_catalog(updated, game)
            accepted.append(game)
        except Exception as error:
            rejected.append({"appId": app_id, "reason": str(error)})
    return updated, accepted, rejected


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--request-delay", default=1.0, type=float)
    parser.add_argument("--timeout", default=15.0, type=float)
    arguments = parser.parse_args()

    try:
        targets = load_targets(arguments.input)
        catalog = catalog_import.load_catalog(arguments.catalog)

        def fetch_app(app_id: str) -> bytes:
            raw, _, _ = steam.fetch(
                app_id,
                "kr",
                "korean",
                arguments.timeout,
            )
            return raw

        updated, accepted, rejected = prepare_batch(
            catalog,
            targets,
            fetch_app,
            arguments.request_delay,
        )
        if arguments.apply and rejected:
            raise ValueError(
                "Batch contains rejected products; catalog was not changed"
            )
        if arguments.apply:
            catalog_import.write_catalog(arguments.catalog, updated)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))

    report = {
        "accepted": accepted,
        "rejected": rejected,
        "applied": arguments.apply,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not arguments.apply:
        print("Preview only; use --apply after reviewing every accepted game.")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
