import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "steam_catalog_search", ROOT / "tools/search_steam_catalog.py"
)
catalog_search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(catalog_search)


class SteamCatalogSearchTest(unittest.TestCase):
    def test_parses_store_candidates(self):
        raw = (ROOT / "tests/fixtures/steam_search_elden_ring.html").read_bytes()
        candidates = catalog_search.parse_results(raw)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["externalProductId"], "1245620")
        self.assertEqual(candidates[0]["title"], "ELDEN RING")
        self.assertEqual(candidates[1]["platforms"], ["Windows", "macOS"])

    def test_respects_result_limit(self):
        raw = (ROOT / "tests/fixtures/steam_search_elden_ring.html").read_bytes()
        self.assertEqual(len(catalog_search.parse_results(raw, 1)), 1)

    def test_hides_demo_candidates(self):
        raw = b'''<a class="search_result_row" data-ds-appid="1"><span class="title">Game Demo</span></a>
<a class="search_result_row" data-ds-appid="2"><span class="title">Full Game</span></a>'''
        candidates = catalog_search.parse_results(raw)
        self.assertEqual([candidate["externalProductId"] for candidate in candidates], ["2"])


if __name__ == "__main__":
    unittest.main()
