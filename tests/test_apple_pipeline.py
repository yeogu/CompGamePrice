import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "apple_pipeline",
    ROOT / "tools" / "run_apple_pipeline.py",
)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline)


class ApplePipelineTest(unittest.TestCase):
    def test_collects_then_imports_with_catalog_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(pipeline.collector, "collect", return_value=1), patch.object(
                pipeline.subprocess,
                "run",
            ) as run:
                run.return_value.returncode = 0
                result = pipeline.run_pipeline(
                    ROOT / "build/game_price_tracker",
                    ROOT / "data/game_catalog.json",
                    output,
                    ROOT / "build/game_prices.db",
                )
            self.assertEqual(result, 0)
            command = run.call_args.args[0]
            environment = run.call_args.kwargs["env"]
            self.assertIn("collect-apple-all", command)
            self.assertEqual(
                environment["GAME_PRICE_DATABASE_PATH"],
                str(ROOT / "build/game_prices.db"),
            )

    def test_does_not_import_when_collection_is_empty(self):
        with patch.object(pipeline.collector, "collect", return_value=0), patch.object(
            pipeline.subprocess,
            "run",
        ) as run:
            self.assertEqual(
                pipeline.run_pipeline(Path("tracker"), Path("catalog"), Path("output")),
                1,
            )
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
