from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_storefront_price_pipeline as pipeline


class StorefrontPricePipelineTest(unittest.TestCase):
    def test_each_store_uses_its_existing_cpp_provider_command(self):
        cases = [
            ("EpicGamesStore", "collect-epic-all"),
            ("NintendoEShop", "collect-nintendo-all"),
            ("GOG", "collect-gog-all"),
            ("MetaQuestStore", "collect-meta-quest-all"),
            ("EAApp", "collect-ea-app-all"),
            ("BattleNet", "collect-battle-net-all"),
            ("ItchIo", "collect-itch-io-all"),
            ("HumbleStore", "collect-humble-store-all"),
        ]
        for store, expected_command in cases:
            collector = pipeline.COLLECTORS[store][0]
            with self.subTest(store=store), tempfile.TemporaryDirectory() as directory:
                with patch.object(collector, "collect", return_value=(1, [])), patch.object(
                    pipeline.subprocess,
                    "run",
                ) as run:
                    run.return_value.returncode = 0
                    result = pipeline.run_pipeline(
                        store,
                        Path("tracker"),
                        Path("catalog"),
                        Path(directory),
                        Path(directory) / "database.db",
                    )
                self.assertEqual(result, 0)
                self.assertIn(expected_command, run.call_args.args[0])
                self.assertEqual(
                    run.call_args.kwargs["env"]["GAME_PRICE_DATABASE_PATH"],
                    str(Path(directory) / "database.db"),
                )

    def test_does_not_import_when_every_product_failed(self):
        collector = pipeline.COLLECTORS["EpicGamesStore"][0]
        with patch.object(collector, "collect", return_value=(0, [("id", "403")])), patch.object(
            pipeline.subprocess,
            "run",
        ) as run:
            result = pipeline.run_pipeline(
                "EpicGamesStore",
                Path("tracker"),
                Path("catalog"),
                Path("output"),
            )
        self.assertEqual(result, 1)
        run.assert_not_called()

    def test_empty_store_is_not_a_collection_failure(self):
        collector = pipeline.COLLECTORS["GOG"][0]
        with patch.object(collector, "collect", return_value=(0, [])), patch.object(
            pipeline.subprocess,
            "run",
        ) as run:
            result = pipeline.run_pipeline(
                "GOG", Path("tracker"), Path("catalog"), Path("output"))
        self.assertEqual(result, 0)
        run.assert_not_called()

    def test_records_provider_failure_before_cpp_import(self):
        collector = pipeline.COLLECTORS["EpicGamesStore"][0]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prices.db"
            with patch.object(
                collector,
                "collect",
                return_value=(0, [("hades", "HTTP 403")]),
            ):
                result = pipeline.run_pipeline(
                    "EpicGamesStore",
                    Path("tracker"),
                    Path("catalog"),
                    Path(directory),
                    database,
                )

            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    """
                    SELECT status, exit_code, error_message
                    FROM catalog_sync_price_collection
                    WHERE provider = 'EpicGamesStore'
                    """
                ).fetchone()

        self.assertEqual(result, 1)
        self.assertEqual(row[0], "FAILED")
        self.assertEqual(row[1], 1)
        self.assertIn("HTTP 403", row[2])

    def test_reports_partial_result_when_some_products_failed(self):
        collector = pipeline.COLLECTORS["EpicGamesStore"][0]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prices.db"
            with patch.object(
                collector,
                "collect",
                return_value=(1, [("broken", "timeout")]),
            ), patch.object(pipeline.subprocess, "run") as run:
                run.return_value.returncode = 0
                result = pipeline.run_pipeline(
                    "EpicGamesStore",
                    Path("tracker"),
                    Path("catalog"),
                    Path(directory),
                    database,
                )
            with sqlite3.connect(database) as connection:
                status = connection.execute(
                    "SELECT status FROM catalog_sync_price_collection "
                    "WHERE provider = 'EpicGamesStore'",
                ).fetchone()[0]
        self.assertEqual(result, 2)
        self.assertEqual(status, "PARTIAL")

    def test_targeted_collection_uses_only_requested_product(self):
        collector = pipeline.COLLECTORS["PlayStationStore"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({
                "schemaVersion": 4,
                "games": [{
                    "id": "game",
                    "title": "Game",
                    "products": [
                        {"store": "PlayStationStore", "productId": "wanted", "productUrl": "https://example.com/wanted"},
                        {"store": "PlayStationStore", "productId": "other", "productUrl": "https://example.com/other"},
                    ],
                }],
            }), encoding="utf-8")

            def collect(store, selected_catalog, output):
                document = json.loads(selected_catalog.read_text(encoding="utf-8"))
                products = document["games"][0]["products"]
                self.assertEqual(store, "PlayStationStore")
                self.assertEqual([product["productId"] for product in products], ["wanted"])
                output.write_text("snapshot", encoding="utf-8")
                return 1, []

            with patch.object(collector, "collect", side_effect=collect), patch.object(
                pipeline.subprocess,
                "run",
            ) as run:
                run.return_value.returncode = 0
                result = pipeline.run_pipeline(
                    "PlayStationStore",
                    Path("tracker"),
                    catalog,
                    root / "output",
                    product_id="wanted",
                )

        self.assertEqual(result, 0)
        self.assertNotEqual(run.call_args.args[0][-1], str(root / "output"))


if __name__ == "__main__":
    unittest.main()
