#!/usr/bin/env python3
"""Report canonical Games whose identity metadata is incomplete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import catalog_storage


REQUIRED_IDENTITY_FIELDS = (
    "developers",
    "publishers",
)


def audit(document: dict) -> dict:
    games = []
    for game in document["games"]:
        missing = [
            field
            for field in REQUIRED_IDENTITY_FIELDS
            if not game.get(field)
        ]
        if missing:
            games.append({
                "gameId": game["id"],
                "title": game["title"],
                "missingFields": missing,
                "storeProductCount": len(game.get("products", [])),
            })
    return {
        "gameCount": len(document["games"]),
        "incompleteCount": len(games),
        "completeCount": len(document["games"]) - len(games),
        "games": games,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default=root / "data/game_catalog.json",
        type=Path,
    )
    parser.add_argument("--fail-on-incomplete", action="store_true")
    arguments = parser.parse_args()
    document = json.loads(arguments.catalog.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(document)
    result = audit(document)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if arguments.fail_on_incomplete and result["incompleteCount"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
