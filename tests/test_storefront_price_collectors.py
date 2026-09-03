import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import collect_epic_snapshot as epic
import collect_nintendo_snapshot as nintendo
import storefront_price_support as support


class StorefrontPriceCollectorsTest(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "schemaVersion": 4,
            "games": [{
                "id": "hades",
                "title": "Hades",
                "platforms": ["Windows", "macOS", "NintendoSwitch"],
                "products": [
                    {
                        "store": "EpicGamesStore",
                        "productId": "hades",
                        "productUrl": "https://store.epicgames.com/p/hades",
                    },
                    {
                        "store": "NintendoEShop",
                        "productId": "70010000033128",
                        "productUrl": "https://store.nintendo.co.kr/70010000033128",
                    },
                ],
            }],
        }

    def test_epic_normalizes_exact_base_game_and_krw_discount(self):
        raw = (ROOT / "tests/fixtures/epic_search_hades.json").read_bytes()
        block = epic.normalized_block(raw, "hades", "hades", "ignored")
        self.assertIn("current_price_krw: 16800", block)
        self.assertIn("regular_price_krw: 28000", block)
        self.assertIn("discount_percent: 40", block)
        self.assertIn("compatible_os: WIN|MAC", block)

    def test_epic_rejects_wrong_currency(self):
        document = json.loads(
            (ROOT / "tests/fixtures/epic_search_hades.json").read_text(),
        )
        price = document["data"]["Catalog"]["searchStore"]["elements"][1]["price"]
        price["totalPrice"]["currencyCode"] = "USD"
        with self.assertRaisesRegex(ValueError, "whole KRW"):
            epic.normalized_block(
                json.dumps(document).encode(),
                "hades",
                "hades",
                "ignored",
            )

    def test_nintendo_normalizes_product_meta_price(self):
        raw = (ROOT / "tests/fixtures/nintendo_hades_product.html").read_bytes()
        row = nintendo.normalized_row(
            raw,
            "70010000033128",
            "hades",
            "ignored",
        )
        self.assertEqual(
            row,
            "70010000033128,hades,28600,28600,0,SWITCH,KR,AVAILABLE,SUPPORTED",
        )

    def test_partial_failure_keeps_successful_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            output = root / "epic.txt"
            catalog = json.loads(json.dumps(self.catalog))
            catalog["games"][0]["products"].insert(0, {
                "store": "EpicGamesStore",
                "productId": "missing",
                "productUrl": "https://store.epicgames.com/p/missing",
            })
            catalog_path.write_text(json.dumps(catalog))
            raw = (ROOT / "tests/fixtures/epic_search_hades.json").read_bytes()

            def fetcher(product_id, game_id, product_url, timeout):
                del game_id
                del product_url
                del timeout
                if product_id == "missing":
                    raise support.PermanentCollectionError("not found")
                return raw

            count, failures = epic.collect(
                catalog_path,
                output,
                max_attempts=2,
                retry_delay=0,
                request_delay=0,
                fetcher=fetcher,
            )
            self.assertEqual(count, 1)
            self.assertEqual(failures, [("missing", "not found")])
            self.assertIn("offer_id: hades", output.read_text())

    def test_transient_failure_retries_with_exponential_backoff(self):
        attempts = 0
        sleeps = []

        def fetcher(product_id, game_id, product_url, timeout):
            nonlocal attempts
            del product_id
            del game_id
            del product_url
            del timeout
            attempts += 1
            if attempts < 3:
                raise TimeoutError("timeout")
            return b"ok"

        rows, failures = support.collect_with_retry(
            [("id", "game", "url")],
            lambda raw, product_id, game_id, product_url: raw.decode(),
            fetcher,
            1,
            3,
            2,
            0,
            sleeper=sleeps.append,
        )
        self.assertEqual(rows, ["ok"])
        self.assertEqual(failures, [])
        self.assertEqual(sleeps, [2, 4])


if __name__ == "__main__":
    unittest.main()
