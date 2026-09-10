from pathlib import Path
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
                )
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
