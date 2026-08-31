#!/usr/bin/env python3
"""Exercise approved mobile catalog products through real tracker imports."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import collect_apple_snapshot
import collect_google_play_snapshot
import run_apple_pipeline
import run_google_play_pipeline


def catalog_document() -> dict:
    return {
        "schemaVersion": 4,
        "games": [{
            "id": "stardew-valley",
            "title": "Stardew Valley",
            "aliases": [],
            "developers": ["ConcernedApe"],
            "publishers": ["ConcernedApe"],
            "genres": ["Simulation"],
            "tags": [],
            "platforms": ["Android", "iOS", "iPadOS"],
            "products": [
                {
                    "store": "GooglePlay",
                    "productId": "com.chucklefish.stardewvalley",
                    "productUrl": "https://play.google.com/store/apps/details?id=com.chucklefish.stardewvalley",
                    "platforms": ["Android"],
                    "region": "KR",
                    "edition": "Standard",
                    "offerType": "BaseGame",
                },
                {
                    "store": "AppleAppStore",
                    "productId": "1406710800",
                    "productUrl": "https://apps.apple.com/kr/app/id1406710800",
                    "platforms": ["iOS", "iPadOS"],
                    "region": "KR",
                    "edition": "Standard",
                    "offerType": "BaseGame",
                },
            ],
        }],
    }


def google_collect_fixture(catalog: Path, output: Path) -> tuple[int, list]:
    del catalog
    raw = (ROOT / "tests/fixtures/google_play_stardew.html").read_bytes()
    block = collect_google_play_snapshot.normalized_block(
        raw,
        "com.chucklefish.stardewvalley",
        "stardew-valley",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(block + "\n", encoding="utf-8")
    return 1, []


def apple_collect_fixture(catalog: Path, output: Path) -> int:
    del catalog
    raw = (ROOT / "tests/fixtures/apple_lookup_1406710800.json").read_bytes()
    row = collect_apple_snapshot.normalized_row(
        raw,
        "1406710800",
        "stardew-valley",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# track_id,canonical_game_id,amount_krw,device_families,available_for_sale\n" +
        row +
        "\n",
        encoding="utf-8",
    )
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: mobile_price_collection_e2e.py TRACKER")
    tracker = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        catalog = root / "catalog.json"
        database = root / "prices.db"
        snapshots = root / "snapshots"
        catalog.write_text(
            json.dumps(catalog_document()),
            encoding="utf-8",
        )
        with patch.object(
            run_google_play_pipeline.collector,
            "collect",
            side_effect=google_collect_fixture,
        ):
            google_result = run_google_play_pipeline.run_pipeline(
                tracker,
                catalog,
                snapshots,
                database,
            )
        with patch.object(
            run_apple_pipeline.collector,
            "collect",
            side_effect=apple_collect_fixture,
        ):
            apple_result = run_apple_pipeline.run_pipeline(
                tracker,
                catalog,
                snapshots,
                database,
            )
        assert google_result == 0
        assert apple_result == 0
        with sqlite3.connect(database) as connection:
            products = connection.execute(
                """
                SELECT store, external_product_id, price_minor, currency
                FROM store_products
                ORDER BY store
                """
            ).fetchall()
            history_count = connection.execute(
                "SELECT COUNT(*) FROM price_history"
            ).fetchone()[0]
        expected_products = [
            ("Apple App Store", "1406710800", 6600, "KRW"),
            ("Google Play", "com.chucklefish.stardewvalley", 5500, "KRW"),
        ]
        assert products == expected_products, products
        assert history_count == 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
