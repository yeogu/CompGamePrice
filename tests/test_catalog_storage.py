import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "catalog_storage",
    ROOT / "tools" / "catalog_storage.py",
)
storage = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(storage)


def game(game_id: str, product_id: str) -> dict:
    return {
        "id": game_id,
        "title": game_id.replace("-", " ").title(),
        "platforms": ["Windows"],
        "products": [
            {
                "store": "Steam",
                "productId": product_id,
                "productUrl": f"https://example.test/{product_id}",
                "platforms": ["Windows"],
                "region": "KR",
                "edition": "Standard",
                "offerType": "BaseGame",
            }
        ],
    }


class CatalogStorageTest(unittest.TestCase):
    def test_existing_duplicate_metadata_is_repaired_on_next_update(self):
        value = game("first", "1")
        value["developers"] = [" Oedipe Games ", "Oedipe Games"]
        self.catalog.write_text(json.dumps({"schemaVersion": 4, "games": [value]}))
        storage.update_catalog(
            self.catalog, lambda current: (current, current["games"][0]),
            store="Steam", product_id="1", game_id="first")
        repaired = json.loads(self.catalog.read_text())
        self.assertEqual(repaired["games"][0]["developers"], ["Oedipe Games"])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.catalog = self.directory / "catalog.json"
        self.database = self.directory / "audit.db"
        self.catalog.write_text(
            json.dumps({"schemaVersion": 4, "games": []}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def add(self, value: dict):
        def updater(current):
            return {
                **current,
                "games": [*current["games"], value],
            }, value
        return updater

    def test_serializes_concurrent_updates_without_losing_a_game(self):
        errors = []

        def run(value):
            try:
                storage.update_catalog(
                    self.catalog,
                    self.add(value),
                    store="Steam",
                    product_id=value["products"][0]["productId"],
                    game_id=value["id"],
                )
            except Exception as error:
                errors.append(error)

        threads = [
            threading.Thread(target=run, args=(game("first", "1"),)),
            threading.Thread(target=run, args=(game("second", "2"),)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        document = json.loads(self.catalog.read_text(encoding="utf-8"))
        self.assertEqual({item["id"] for item in document["games"]}, {"first", "second"})

    def test_restores_original_when_audit_commit_path_fails(self):
        original = self.catalog.read_bytes()
        with patch.object(storage, "finish_audit", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                storage.update_catalog(
                    self.catalog,
                    self.add(game("first", "1")),
                    store="Steam",
                    product_id="1",
                    game_id="first",
                    database_path=self.database,
                )

        self.assertEqual(self.catalog.read_bytes(), original)

    def test_records_applied_and_no_op_audit_events(self):
        first = game("first", "1")
        storage.update_catalog(
            self.catalog,
            self.add(first),
            store="Steam",
            product_id="1",
            game_id="first",
            database_path=self.database,
        )
        storage.update_catalog(
            self.catalog,
            lambda current: (current, first),
            store="Steam",
            product_id="1",
            game_id="first",
            database_path=self.database,
        )

        with sqlite3.connect(self.database) as connection:
            outcomes = connection.execute(
                "SELECT outcome FROM catalog_change_audit ORDER BY id"
            ).fetchall()
        self.assertEqual(outcomes, [("APPLIED",), ("NO_OP",)])

    def test_rejects_duplicate_product_before_replacing_file(self):
        original = self.catalog.read_bytes()
        duplicate_document = {
            "schemaVersion": 4,
            "games": [game("first", "1"), game("second", "1")],
        }
        with self.assertRaisesRegex(ValueError, "Duplicate Store product"):
            storage.update_catalog(
                self.catalog,
                lambda current: (duplicate_document, None),
                store="Steam",
                product_id="1",
                game_id="second",
            )
        self.assertEqual(self.catalog.read_bytes(), original)

    def test_rejects_duplicate_normalized_title_before_replacing_file(self):
        original = self.catalog.read_bytes()
        first = game("first", "1")
        second = game("second", "2")
        second["title"] = "  FIRST  "
        duplicate_document = {
            "schemaVersion": 4,
            "games": [first, second],
        }
        with self.assertRaisesRegex(ValueError, "Duplicate Game Catalog identity: second"):
            storage.update_catalog(
                self.catalog,
                lambda current: (duplicate_document, None),
                store="Steam",
                product_id="2",
                game_id="second",
            )
        self.assertEqual(self.catalog.read_bytes(), original)

    def test_rejects_alias_colliding_with_another_title(self):
        first = game("first", "1")
        second = game("second", "2")
        second["aliases"] = ["First"]
        with self.assertRaisesRegex(ValueError, "Duplicate Game Catalog identity: second"):
            storage.validate_catalog({"schemaVersion": 4, "games": [first, second]})

    def test_rejects_duplicate_normalized_alias_within_game(self):
        value = game("first", "1")
        value["aliases"] = ["Alternate", " alternate "]
        with self.assertRaisesRegex(ValueError, "Invalid or duplicate Game Catalog alias"):
            storage.validate_catalog({"schemaVersion": 4, "games": [value]})

    def test_rejects_missing_game_platforms_before_replacing_file(self):
        original = self.catalog.read_bytes()
        invalid = game("missing-platforms", "2")
        invalid.pop("platforms")
        with self.assertRaisesRegex(ValueError, "platforms must be a non-empty array"):
            storage.update_catalog(
                self.catalog,
                self.add(invalid),
                store="Steam",
                product_id="2",
                game_id="missing-platforms",
            )
        self.assertEqual(self.catalog.read_bytes(), original)

    def test_rejects_product_platform_outside_game_platforms(self):
        invalid = game("platform-mismatch", "2")
        invalid["products"][0]["platforms"] = ["Linux"]
        with self.assertRaisesRegex(ValueError, "not supported by its Game"):
            storage.validate_catalog({"schemaVersion": 4, "games": [invalid]})


if __name__ == "__main__":
    unittest.main()
