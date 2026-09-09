import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "catalog_artwork_backfill",
    ROOT / "tools" / "backfill_catalog_artwork.py",
)
backfill = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backfill)


class CatalogArtworkBackfillTest(unittest.TestCase):
    @staticmethod
    def inspect(url, timeout):
        del timeout
        score = 95 if "store.test" in url or "mobile.test" in url else 20
        return SimpleNamespace(score=score)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.catalog = directory / "catalog.json"
        self.database = directory / "prices.db"
        self.catalog.write_text(
            json.dumps({
                "schemaVersion": 4,
                "games": [
                    {
                        "id": "missing-art",
                        "title": "Missing Art",
                        "aliases": [],
                        "developers": [],
                        "publishers": [],
                        "genres": [],
                        "tags": [],
                        "platforms": ["Windows"],
                        "products": [
                            {
                                "store": "GooglePlay",
                                "productId": "game.mobile",
                                "productUrl": "https://example.test/mobile",
                            },
                            {
                                "store": "PlayStationStore",
                                "productId": "GAME-1",
                                "productUrl": "https://example.test/console",
                            },
                        ],
                    },
                    {
                        "id": "custom-art",
                        "title": "Custom Art",
                        "imageUrl": "https://admin.test/custom.jpg",
                        "aliases": [],
                        "developers": [],
                        "publishers": [],
                        "genres": [],
                        "tags": [],
                        "platforms": ["Windows"],
                        "products": [],
                    },
                ],
            }),
            encoding="utf-8",
        )
        sqlite3.connect(self.database).close()

    def tearDown(self):
        self.temporary.cleanup()

    def test_uses_store_priority_and_preserves_existing_artwork(self):
        calls = []

        def fetch(product, timeout):
            calls.append((product["store"], timeout))
            return "https://store.test/art.jpg"

        result = backfill.backfill(
            self.catalog,
            self.database,
            limit=10,
            timeout=3.0,
            image_fetcher=fetch,
            image_inspector=self.inspect,
        )

        document = json.loads(self.catalog.read_text(encoding="utf-8"))
        self.assertEqual(calls, [("PlayStationStore", 3.0)])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(document["games"][0]["imageUrl"], "https://store.test/art.jpg")
        self.assertEqual(document["games"][1]["imageUrl"], "https://admin.test/custom.jpg")

    def test_falls_back_when_preferred_store_fails(self):
        calls = []

        def fetch(product, timeout):
            del timeout
            calls.append(product["store"])
            if product["store"] == "PlayStationStore":
                raise RuntimeError("unavailable")
            return "https://mobile.test/art.jpg"

        result = backfill.backfill(
            self.catalog,
            self.database,
            image_fetcher=fetch,
            image_inspector=self.inspect,
        )

        self.assertEqual(calls, ["PlayStationStore", "GooglePlay"])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["failed"], [])

    def test_prefers_wide_store_artwork_over_low_quality_existing_image(self):
        document = json.loads(self.catalog.read_text(encoding="utf-8"))
        document["games"][0]["imageUrl"] = "https://nintendo.test/boxed.jpg"
        self.catalog.write_text(json.dumps(document), encoding="utf-8")

        def inspect(url, timeout):
            del timeout
            score = 25 if "nintendo.test" in url else 90
            return SimpleNamespace(score=score)

        result = backfill.backfill(
            self.catalog,
            self.database,
            image_fetcher=lambda product, timeout: "https://steam.test/header.jpg",
            image_inspector=inspect,
        )

        updated = json.loads(self.catalog.read_text(encoding="utf-8"))
        self.assertEqual(result["updated"], 1)
        self.assertEqual(
            updated["games"][0]["imageUrl"],
            "https://steam.test/header.jpg",
        )


if __name__ == "__main__":
    unittest.main()
