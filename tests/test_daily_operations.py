import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "daily_operations", ROOT / "tools" / "run_daily_operations.py"
)
daily_operations = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daily_operations)


class DailyOperationsTest(unittest.TestCase):
    def test_maintenance_has_no_price_collection(self):
        with patch.object(daily_operations, "run_step", side_effect=lambda name, command, environment: {"name": name, "exitCode": 0}):
            results = daily_operations.run_operations(ROOT, Path("tracker"), Path("db"), Path("output"), None, mode="maintenance")
        self.assertIn("steam-metadata-sync", [row["name"] for row in results])
        self.assertNotIn("steam-discovery", [row["name"] for row in results])
        self.assertNotIn("steam-catalog-sync", [row["name"] for row in results])
        self.assertNotIn("steam", [row["name"] for row in results])

    def test_catalog_growth_is_independent_of_slow_metadata_and_cross_store_matching(self):
        import catalog_growth
        with patch.object(catalog_growth, "run_growth", return_value=[]) as growth, patch.object(daily_operations, "run_step") as step:
            daily_operations.run_operations(ROOT, Path("tracker"), Path("db"), Path("output"), None, 100, steam_discovery_pages=2, mode="catalog")
        growth.assert_called_once()
        step.assert_not_called()

    def test_prices_delegate_to_full_inventory_without_discovery(self):
        import daily_price_refresh
        with patch.object(daily_price_refresh, "run_refresh", return_value=[{"name": "daily-prices", "exitCode": 0}]) as refresh, patch.object(daily_operations, "run_step", side_effect=lambda name, command, environment: {"name": name, "exitCode": 0}):
            results = daily_operations.run_operations(ROOT, Path("tracker"), Path("db"), Path("output"), None, mode="prices")
        refresh.assert_called_once()
        self.assertEqual([row["name"] for row in results], ["daily-prices", "ecb-exchange-rates", "collection-health"])
    def test_classifies_success_partial_warning_and_failure(self):
        self.assertEqual(daily_operations.step_outcome("steam", 0), "SUCCEEDED")
        self.assertEqual(daily_operations.step_outcome("epic-games", 2), "PARTIAL")
        self.assertEqual(
            daily_operations.step_outcome("collection-health", 1),
            "WARNING",
        )
        self.assertEqual(
            daily_operations.step_outcome("ecb-exchange-rates", 1),
            "WARNING",
        )
        self.assertEqual(daily_operations.step_outcome("steam", 1), "FAILED")

    def test_runs_provider_jobs_independently_and_continues_after_failure(self):
        exit_codes = iter(
            [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]
        )

        def fake_run(name, command, environment):
            self.assertTrue(command)
            self.assertIn("GAME_PRICE_DATABASE_PATH", environment)
            self.assertIn("GAME_PRICE_CATALOG_PATH", environment)
            return {"name": name, "exitCode": next(exit_codes)}

        with patch.object(daily_operations, "run_step", side_effect=fake_run) as run_step:
            results = daily_operations.run_operations(
                ROOT,
                ROOT / "build/game_price_tracker",
                ROOT / "build/game_prices.db",
                ROOT / "snapshots/latest",
                ROOT / "snapshots/outbox.jsonl",
            )

        discovery = next(
            command
            for name, command, _ in [call.args for call in run_step.call_args_list]
            if name == "steam-discovery"
        )
        self.assertIn("75", discovery)
        self.assertIn("4", discovery)
        metadata = next(
            command
            for name, command, _ in [call.args for call in run_step.call_args_list]
            if name == "steam-metadata-sync"
        )
        self.assertIn("20", metadata)

        self.assertEqual(
            [result["name"] for result in results],
            [
                "ecb-exchange-rates",
                "steam-discovery",
                "steam-catalog-sync",
                "steam-metadata-sync",
                "store-artwork-backfill",
                "google-play-catalog-discovery",
                "apple-catalog-discovery",
                "nintendo-catalog-discovery",
                "playstation-catalog-discovery",
                "microsoft-catalog-discovery",
                "steam",
                "epic-games",
                "ubisoft-store",
                "gog",
                "meta-quest-store",
                "ea-app",
                "battle-net",
                "itch-io",
                "humble-store",
                "nintendo-eshop",
                "playstation-store",
                "microsoft-store",
                "google-play",
                "apple",
                "collection-health",
                "notification-outbox",
            ],
        )
        self.assertEqual(results[1]["exitCode"], 1)
        self.assertEqual(len(results), 26)


if __name__ == "__main__":
    unittest.main()
