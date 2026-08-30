import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "apple_search",
    ROOT / "tools" / "search_apple_catalog.py",
)
search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(search)


class AppleCatalogSearchTest(unittest.TestCase):
    def test_parses_identity_price_and_supported_devices(self):
        raw = (ROOT / "tests/fixtures/apple_search_stardew.json").read_bytes()
        candidate = search.parse_results(raw)[0]
        self.assertEqual(candidate["externalProductId"], "1406710800")
        self.assertEqual(candidate["developer"], "ConcernedApe")
        self.assertEqual(candidate["platforms"], ["iOS", "iPadOS"])
        self.assertEqual(candidate["priceMinor"], 6600)


if __name__ == "__main__":
    unittest.main()
