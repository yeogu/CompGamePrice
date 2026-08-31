import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "apple_collector", ROOT / "tools" / "collect_apple_snapshot.py"
)
apple_collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(apple_collector)


class AppleCollectorTest(unittest.TestCase):
    def test_uses_catalog_track_id_and_normalizes_krw_price(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(json.dumps({
                "games": [{
                    "id": "stardew-valley",
                    "products": [{
                        "store": "AppleAppStore",
                        "productId": "1406710800",
                    }],
                }],
            }), encoding="utf-8")
            self.assertEqual(
                apple_collector.apple_targets(catalog),
                [("1406710800", "stardew-valley")],
            )
        raw = (ROOT / "tests/fixtures/apple_lookup_1406710800.json").read_bytes()
        self.assertEqual(
            apple_collector.normalized_row(raw, "1406710800", "stardew-valley"),
            "1406710800,stardew-valley,6600,IPHONE+IPAD,true",
        )

    def test_rejects_wrong_currency(self):
        raw = b'{"resultCount":1,"results":[{"trackId":1406710800,"currency":"USD","price":4.99,"supportedDevices":["iPhone"]}]}'
        with self.assertRaisesRegex(ValueError, "currency"):
            apple_collector.normalized_row(raw, "1406710800", "stardew-valley")


if __name__ == "__main__":
    unittest.main()
