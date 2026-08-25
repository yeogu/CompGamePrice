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


if __name__ == "__main__":
    unittest.main()
