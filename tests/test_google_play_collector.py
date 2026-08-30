import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "google_play_collector",
    ROOT / "tools" / "collect_google_play_snapshot.py",
)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collector)


class GooglePlayCollectorTest(unittest.TestCase):
    def test_normalizes_registered_krw_offer(self):
        raw = (ROOT / "tests/fixtures/google_play_stardew.html").read_bytes()
        self.assertEqual(
            collector.normalized_block(
                raw,
                "com.chucklefish.stardewvalley",
                "stardew-valley",
            ),
            "package_name=com.chucklefish.stardewvalley\n"
            "game_id=stardew-valley\n"
            "price_micros=5500000000\n"
            "published=true",
        )

    def test_partial_failure_does_not_discard_successful_products(self):
        raw = (ROOT / "tests/fixtures/google_play_stardew.html").read_bytes()
        attempts = {}

        def fake_fetch(package_name, _timeout):
            attempts[package_name] = attempts.get(package_name, 0) + 1
            if package_name == "broken.package":
                raise TimeoutError("timed out")
            return raw

        catalog = {
            "games": [
                {"id": "good", "products": [{"store": "GooglePlay", "productId": "good.package"}]},
                {"id": "broken", "products": [{"store": "GooglePlay", "productId": "broken.package"}]},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.json"
            output_path = Path(directory) / "google_play_products.txt"
            catalog_path.write_text(__import__("json").dumps(catalog), encoding="utf-8")
            count, failures = collector.collect(
                catalog_path,
                output_path,
                max_attempts=2,
                retry_delay=0,
                fetcher=fake_fetch,
            )
            self.assertEqual(count, 1)
            self.assertEqual(failures, [("broken.package", "timed out")])
            self.assertIn("good.package", output_path.read_text(encoding="utf-8"))
            self.assertEqual(attempts["broken.package"], 2)

    def test_rejects_wrong_currency(self):
        raw = b'<script type="application/ld+json">{"@type":"SoftwareApplication","offers":{"price":"4","priceCurrency":"USD"}}</script>'
        with self.assertRaisesRegex(ValueError, "currency"):
            collector.normalized_block(raw, "package", "game")


if __name__ == "__main__":
    unittest.main()
