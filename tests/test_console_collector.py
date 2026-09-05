import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import collect_console_snapshot


PLAYSTATION_PRODUCT = b"""
<script type="application/ld+json">
{"@type":"Product","name":"Hades","sku":"UP2125-CUSA27387_00-3466019145463410",
 "offers":{"price":"26000","priceCurrency":"KRW"}}
</script><span>PS4</span>
"""


class ConsoleCollectorTest(unittest.TestCase):
    def test_collects_registered_product_with_exact_generation(self):
        catalog = {
            "games": [{
                "id": "hades",
                "products": [{
                    "store": "PlayStationStore",
                    "productId": "UP2125-CUSA27387_00-3466019145463410",
                    "productUrl": "https://store.playstation.com/ko-kr/product/UP2125-CUSA27387_00-3466019145463410",
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.json"
            output_path = Path(directory) / "snapshot.csv"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            collected, failures = collect_console_snapshot.collect(
                "PlayStationStore",
                catalog_path,
                output_path,
                request_delay=0,
                retry_delay=0,
                fetcher=lambda *_: PLAYSTATION_PRODUCT,
            )
            self.assertEqual(collected, 1)
            self.assertEqual(failures, [])
            self.assertIn(",PS4,KR,AVAILABLE", output_path.read_text())

    def test_missing_console_generation_is_quarantined(self):
        raw = PLAYSTATION_PRODUCT.replace(b"PS4", b"console")
        catalog = {
            "games": [{
                "id": "hades",
                "products": [{
                    "store": "PlayStationStore",
                    "productId": "UP2125-CUSA27387_00-3466019145463410",
                    "productUrl": "https://store.playstation.com/ko-kr/product/UP2125-CUSA27387_00-3466019145463410",
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.json"
            output_path = Path(directory) / "snapshot.csv"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            collected, failures = collect_console_snapshot.collect(
                "PlayStationStore",
                catalog_path,
                output_path,
                request_delay=0,
                retry_delay=0,
                fetcher=lambda *_: raw,
            )
            self.assertEqual(collected, 0)
            self.assertEqual(len(failures), 1)
            self.assertIn("console generation", failures[0][1])
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
