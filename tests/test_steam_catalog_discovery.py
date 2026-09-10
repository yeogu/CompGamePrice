import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.error import HTTPError


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
            "popularnew": self.html("20", "New Game"),
            "newreleases": self.html("20", "New Game"),
            "comingsoon": self.html("30", "Upcoming Game"),
        }

        def fetch(parameters):
            return responses[parameters.get("filter", "specials")]

        candidates = discovery.discover(fetch, 10, 1)
        self.assertEqual(
            [candidate["appId"] for candidate in candidates],
            ["10", "20", "30"],
        )
        self.assertEqual(candidates[0]["source"], "top-sellers")
        self.assertEqual(candidates[1]["source"], "popular-new")

    def test_fetches_multiple_bounded_pages_per_source(self):
        pages = []

        def fetch(parameters):
            pages.append((parameters.get("filter", "specials"), parameters["page"]))
            return self.html(parameters["page"], f"Game {parameters['page']}")

        candidates = discovery.discover(fetch, 10, 2)

        self.assertEqual(len(pages), 10)
        self.assertEqual({page for _, page in pages}, {"1", "2"})
        self.assertEqual([candidate["appId"] for candidate in candidates], ["1", "2"])

    def test_continues_with_other_sources_after_rate_limit(self):
        failures = []

        def fetch(parameters):
            if parameters.get("filter") == "topsellers":
                raise HTTPError("url", 429, "Too Many Requests", {}, None)
            return self.html("20", "Available Game")

        candidates = discovery.discover(fetch, 10, 1, failures=failures)

        self.assertEqual([candidate["appId"] for candidate in candidates], ["20"])
        self.assertEqual(failures[0]["source"], "top-sellers")
        self.assertEqual(failures[0]["page"], 1)

    def test_fetch_source_retries_rate_limit_with_bounded_backoff(self):
        attempts = []
        delays = []
        original_urlopen = discovery.urlopen

        def rate_limited(*args, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise HTTPError("url", 429, "Too Many Requests", {}, None)

            class Response:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b"ok"

            return Response()

        discovery.urlopen = rate_limited
        try:
            result = discovery.fetch_source(
                {"filter": "topsellers"},
                max_attempts=3,
                retry_delay=1.0,
                sleeper=delays.append,
            )
        finally:
            discovery.urlopen = original_urlopen

        self.assertEqual(result, b"ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(delays, [1.0, 2.0])

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
