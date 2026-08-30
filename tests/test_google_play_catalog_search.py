import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "google_play_search",
    ROOT / "tools" / "search_google_play_catalog.py",
)
search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(search)


class GooglePlayCatalogSearchTest(unittest.TestCase):
    def test_parses_package_title_and_android_platform(self):
        raw = (ROOT / "tests/fixtures/google_play_search.html").read_bytes()
        results = search.parse_results(raw)
        self.assertEqual(results[0]["externalProductId"], "com.chucklefish.stardewvalley")
        self.assertEqual(results[0]["platforms"], ["Android"])
        self.assertEqual(len(results), 2)

    def test_deduplicates_packages(self):
        raw = b'<a href="/store/apps/details?id=one.game" aria-label="One"></a><a href="/store/apps/details?id=one.game" aria-label="Duplicate"></a>'
        self.assertEqual(len(search.parse_results(raw)), 1)


if __name__ == "__main__":
    unittest.main()
