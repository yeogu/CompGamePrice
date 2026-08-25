import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "steam_collector", ROOT / "tools" / "collect_steam_snapshot.py"
)
steam_collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(steam_collector)


class SteamCollectorTest(unittest.TestCase):
    def test_writes_raw_metadata_and_provider_snapshot(self):
        raw = (ROOT / "tests" / "fixtures" / "steam_appdetails_413150.json").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            steam_collector.write_snapshot(
                raw,
                output,
                "413150",
                "stardew-valley",
                "fixture://steam",
                200,
            )

            product_lines = (output / "steam_products.txt").read_text().splitlines()
            self.assertEqual(
                product_lines[-1],
                "413150|stardew-valley|16000|windows,mac,linux|true",
            )
            self.assertEqual((output / "steam_413150.json").read_bytes(), raw)
            metadata = json.loads(
                (output / "steam_413150.metadata.json").read_text()
            )
            self.assertEqual(metadata["store"], "Steam")
            self.assertEqual(metadata["httpStatus"], 200)
            self.assertEqual(len(metadata["sha256"]), 64)

    def test_rejects_a_response_without_krw_price(self):
        raw = b'{"413150":{"success":true,"data":{"steam_appid":413150,"platforms":{"windows":true}}}}'
        with self.assertRaisesRegex(ValueError, "no KRW price"):
            steam_collector.normalized_row(raw, "413150", "stardew-valley")

    def test_loads_and_validates_collection_targets(self):
        targets = steam_collector.load_targets(
            ROOT / "data" / "steam_collection_targets.json"
        )
        self.assertEqual(
            targets,
            [("413150", "stardew-valley"), ("105600", "terraria")],
        )

        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(
                '{"targets":[{"appId":"413150","gameId":"one"},'
                '{"appId":"413150","gameId":"two"}]}'
            )
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                steam_collector.load_targets(invalid)

    def test_batch_retries_and_isolates_failed_games(self):
        fixture = (
            ROOT / "tests" / "fixtures" / "steam_appdetails_413150.json"
        ).read_bytes()
        attempts = {}
        sleeps = []

        def fake_fetch(app_id, _country, _language, _timeout):
            attempts[app_id] = attempts.get(app_id, 0) + 1
            if app_id == "999":
                raise RuntimeError("temporary Steam failure")
            return fixture, 200, f"fixture://{app_id}"

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            successes, failures = steam_collector.collect_targets(
                [("413150", "stardew-valley"), ("999", "missing-game")],
                output,
                "kr",
                "korean",
                5,
                request_delay=2,
                max_attempts=3,
                retry_delay=1,
                fetcher=fake_fetch,
                sleeper=sleeps.append,
            )

            self.assertEqual(successes, 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(attempts, {"413150": 1, "999": 3})
            self.assertEqual(sleeps, [2, 1, 2])
            products = (output / "steam_products.txt").read_text()
            self.assertIn("413150|stardew-valley|16000", products)
            self.assertNotIn("missing-game", products)
            error = json.loads((output / "steam_999.error.json").read_text())
            self.assertEqual(error["attempts"], 3)
            self.assertEqual(error["error"], "temporary Steam failure")


if __name__ == "__main__":
    unittest.main()
