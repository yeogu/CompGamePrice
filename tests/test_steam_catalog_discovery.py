import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "steam_catalog_discovery",
    ROOT / "tools/discover_steam_catalog.py",
)
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)


class SteamCatalogDiscoveryTest(unittest.TestCase):
    def html(self, app_id, title):
        return f'''<a class="search_result_row" data-ds-appid="{app_id}">
        <span class="title">{title}</span><span class="platform_img win"></span></a>'''.encode()

    def test_deduplicates_sources_and_keeps_highest_priority(self):
        responses = {
            "topsellers": self.html("10", "Popular Game"),
            "specials": self.html("10", "Popular Game"),
            "newreleases": self.html("20", "New Game"),
        }

        def fetch(parameters):
            return responses[parameters.get("filter", "specials")]

        candidates = discovery.discover(fetch, 10)
        self.assertEqual([candidate["appId"] for candidate in candidates], ["10", "20"])
        self.assertEqual(candidates[0]["source"], "top-sellers")

    def test_enqueues_candidates_for_priority_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            count = discovery.enqueue(
                database,
                [{"appId": "10", "title": "Game", "source": "specials", "priority": 200}],
            )
            self.assertEqual(count, 1)
            with sqlite3.connect(database) as connection:
                queued = discovery.catalog_sync.queued_discovery_apps(connection, 10)
            self.assertEqual(queued, [{"appId": "10", "name": "Game"}])


if __name__ == "__main__":
    unittest.main()
