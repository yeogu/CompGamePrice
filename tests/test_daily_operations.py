import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "daily_operations", ROOT / "tools" / "run_daily_operations.py"
)
daily_operations = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daily_operations)


class DailyOperationsTest(unittest.TestCase):
    def test_runs_provider_jobs_independently_and_continues_after_failure(self):
        exit_codes = iter([1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0])

        def fake_run(name, command, environment):
            self.assertTrue(command)
            self.assertIn("GAME_PRICE_DATABASE_PATH", environment)
            self.assertIn("GAME_PRICE_CATALOG_PATH", environment)
            return {"name": name, "exitCode": next(exit_codes)}

        with patch.object(daily_operations, "run_step", side_effect=fake_run):
            results = daily_operations.run_operations(
                ROOT,
                ROOT / "build/game_price_tracker",
                ROOT / "build/game_prices.db",
                ROOT / "snapshots/latest",
                ROOT / "snapshots/outbox.jsonl",
            )

        self.assertEqual(
            [result["name"] for result in results],
            [
                "steam-discovery",
                "steam-catalog-sync",
                "google-play-catalog-discovery",
                "apple-catalog-discovery",
                "nintendo-catalog-discovery",
                "steam",
                "epic-games",
                "nintendo-eshop",
                "google-play",
                "apple",
                "collection-health",
                "notification-outbox",
            ],
        )
        self.assertEqual(results[0]["exitCode"], 1)
        self.assertEqual(len(results), 12)


if __name__ == "__main__":
    unittest.main()
