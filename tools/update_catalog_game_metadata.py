#!/usr/bin/env python3
"""Preview or apply canonical Game metadata changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import catalog_storage


EDITABLE_FIELDS = (
    "title",
    "aliases",
    "developers",
    "publishers",
    "genres",
    "tags",
    "platforms",
)


class MetadataUpdateError(ValueError):
    pass


def normalized_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise MetadataUpdateError(f"{field} must be an array")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MetadataUpdateError(f"{field} must contain non-empty strings")
        normalized = item.strip()
        if normalized not in result:
            result.append(normalized)
    return result


def validated_changes(payload: dict) -> dict:
    unknown = set(payload) - set(EDITABLE_FIELDS)
    if unknown:
        raise MetadataUpdateError(
            f"Unsupported metadata field: {sorted(unknown)[0]}"
        )
    changes = {}
    for field, value in payload.items():
        if field == "title":
            if not isinstance(value, str) or not value.strip():
                raise MetadataUpdateError("title must be a non-empty string")
            changes[field] = value.strip()
        else:
            changes[field] = normalized_string_list(value, field)
    if not changes:
        raise MetadataUpdateError("At least one metadata field is required")
    return changes


def changed_catalog(
    catalog: dict,
    game_id: str,
    changes: dict,
) -> tuple[dict, dict]:
    game = next(
        (item for item in catalog["games"] if item.get("id") == game_id),
        None,
    )
    if game is None:
        raise MetadataUpdateError("Canonical game ID does not exist")
    updated_game = {
        **game,
        **changes,
    }
    diff = {
        field: {
            "before": game.get(field),
            "after": updated_game.get(field),
        }
        for field in changes
        if game.get(field) != updated_game.get(field)
    }
    updated_games = [
        updated_game if item is game else item
        for item in catalog["games"]
    ]
    return {
        **catalog,
        "games": updated_games,
    }, {
        "game": updated_game,
        "diff": diff,
        "changed": bool(diff),
    }


def update_metadata(
    catalog_path: Path,
    game_id: str,
    payload: dict,
    apply: bool,
    database_path: Path | None = None,
) -> dict:
    changes = validated_changes(payload)

    def update(current: dict) -> tuple[dict, dict]:
        return changed_catalog(current, game_id, changes)

    if apply:
        preview_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog_storage.validate_catalog(preview_catalog)
        _, preview = changed_catalog(preview_catalog, game_id, changes)
        result, _ = catalog_storage.update_catalog(
            catalog_path,
            update,
            store="CanonicalCatalog",
            product_id=game_id,
            game_id=game_id,
            database_path=database_path,
            action="UPDATE_GAME_METADATA",
            detail=json.dumps(preview["diff"], ensure_ascii=False),
        )
        return result
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_storage.validate_catalog(catalog)
    _, result = changed_catalog(catalog, game_id, changes)
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--catalog", default=root / "data/game_catalog.json", type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        payload = json.loads(arguments.input.read_text(encoding="utf-8"))
        result = update_metadata(
            arguments.catalog,
            arguments.game_id,
            payload,
            arguments.apply,
            arguments.database,
        )
    except (json.JSONDecodeError, MetadataUpdateError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
