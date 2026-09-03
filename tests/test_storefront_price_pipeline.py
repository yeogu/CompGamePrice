from pathlib import Path
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
                        Path("database"),
                    )
                self.assertEqual(result, 0)
                self.assertIn(expected_command, run.call_args.args[0])
                self.assertEqual(
                    run.call_args.kwargs["env"]["GAME_PRICE_DATABASE_PATH"],
                    "database",
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


if __name__ == "__main__":
    unittest.main()
