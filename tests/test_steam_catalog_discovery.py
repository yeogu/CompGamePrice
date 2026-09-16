import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch


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

        self.assertEqual(len(pages), len(discovery.SOURCES) * 2)
        self.assertEqual({page for _, page in pages}, {"1", "2"})
        self.assertEqual([candidate["appId"] for candidate in candidates], ["1", "2"])

    def test_stops_all_sources_after_rate_limit(self):
        failures = []
        requests = []

        def fetch(parameters):
            requests.append(parameters)
            if parameters.get("filter") == "topsellers":
                raise HTTPError("url", 429, "Too Many Requests", {}, None)
            return self.html("20", "Available Game")

        candidates = discovery.discover(fetch, 10, 1, failures=failures)

        self.assertEqual(candidates, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(failures[0]["source"], "top-sellers")
        self.assertEqual(failures[0]["page"], 1)
        self.assertEqual(failures[0]["httpStatus"], 429)

    def test_fetch_source_retries_server_failure_with_bounded_backoff(self):
        attempts = []
        delays = []
        original_urlopen = discovery.urlopen

        def rate_limited(*args, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise HTTPError("url", 503, "Unavailable", {}, None)

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

    def test_rate_limit_is_not_retried_inside_source_request(self):
        with patch.object(discovery, "urlopen", side_effect=HTTPError(
            "url", 429, "Too Many Requests", {"Retry-After": "1800"}, None,
        )) as request:
            with self.assertRaises(HTTPError):
                discovery.fetch_source({"filter": "topsellers"}, sleeper=lambda _: self.fail("unexpected retry"))
        self.assertEqual(request.call_count, 1)
        url = request.call_args.args[0].full_url
        self.assertIn("category1=998", url)
        self.assertIn("cc=kr", url)

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

    def test_rediscovery_counts_only_new_pending_candidates_and_preserves_queue_age(self):
        candidates = [{"appId": "10", "title": "Game", "source": "specials", "priority": 200}]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            self.assertEqual(discovery.enqueue(database, candidates), 1)
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE catalog_discovery_candidates SET discovered_at = '2020-01-01'")
                connection.execute(
                    "INSERT INTO catalog_sync_seen VALUES('Steam', '20', 'ACCEPTED', '2020-01-01')"
                )
            self.assertEqual(discovery.enqueue(database, candidates + [
                {"appId": "20", "title": "Registered", "source": "specials", "priority": 200}
            ]), 0)
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT external_product_id, status, discovered_at FROM catalog_discovery_candidates ORDER BY external_product_id"
                ).fetchall()
            self.assertEqual(rows[0], ("10", "PENDING", "2020-01-01"))
            self.assertEqual(rows[1][1], "PROCESSED")

    def test_repeated_jobs_resume_next_pages_instead_of_searching_same_head(self):
        requests = []

        def fetch(parameters):
            source = parameters.get("filter", parameters.get("sort_by", "specials"))
            requests.append((source, int(parameters["page"])))
            return self.html(parameters["page"], f"Game {parameters['page']}")

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            first = discovery.run_discovery(database, fetcher=fetch, pages_per_source=2, request_delay=0)
            second = discovery.run_discovery(database, fetcher=fetch, pages_per_source=2, request_delay=0)
            self.assertEqual(first["queued"], 2)
            self.assertEqual(second["queued"], 2)
            self.assertEqual(second["pending"], 4)
            self.assertEqual(set(second["nextPages"].values()), {5})
            self.assertEqual([page for source, page in requests if source == "topsellers"], [1, 2, 3, 4])

    def test_empty_last_page_wraps_and_existing_candidates_are_reported_truthfully(self):
        def fetch(parameters):
            return self.html("10", "Game") if parameters["page"] == "1" else b'<div id="search_resultsRows"></div>'

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            first = discovery.run_discovery(database, fetcher=fetch, pages_per_source=2, request_delay=0)
            second = discovery.run_discovery(database, fetcher=fetch, pages_per_source=2, request_delay=0)
            self.assertEqual(first["queued"], 1)
            self.assertEqual(second["queued"], 0)
            self.assertEqual(second["discovered"], 1)
            self.assertEqual(second["existing"], 1)
            self.assertEqual(set(second["nextPages"].values()), {1})

    def test_bounded_jobs_reach_over_thousand_unique_games_without_revisiting_pages(self):
        source_ids = {source: index + 1 for index, (source, _, _) in enumerate(discovery.SOURCES)}
        calls = []

        def fetch(parameters):
            source = next(source for source, _, query in discovery.SOURCES if all(
                parameters.get(key) == value for key, value in query.items()
            ))
            page = int(parameters["page"])
            calls.append((source, page))
            offset = source_ids[source] * 100000 + page * 100
            return b"".join(self.html(str(offset + item), f"Game {offset + item}") for item in range(50))

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            first = discovery.run_discovery(database, fetcher=fetch, request_delay=0)
            second = discovery.run_discovery(database, fetcher=fetch, request_delay=0)
            self.assertEqual(first["queued"], 600)
            self.assertEqual(second["queued"], 600)
            self.assertEqual(second["pending"], 1200)
            self.assertEqual(len(calls), len(set(calls)))

    def test_rate_limit_persists_successful_pages_and_cooldown_across_jobs(self):
        requests = []

        def fetch(parameters):
            requests.append(parameters["page"])
            if parameters["page"] == "2":
                raise HTTPError("url", 429, "Too Many Requests", {"Retry-After": "1800"}, None)
            return self.html("10", "First page")

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            first = discovery.run_discovery(database, fetcher=fetch, request_delay=0, clock=lambda: 1000)
            second = discovery.run_discovery(database, fetcher=fetch, request_delay=0, clock=lambda: 1100)
            self.assertEqual(first["status"], "PARTIAL")
            self.assertEqual(first["queued"], 1)
            self.assertEqual(first["nextPages"]["top-sellers"], 2)
            self.assertEqual(second["status"], "DEFERRED")
            self.assertEqual(second["retryAfterSeconds"], 1700)
            self.assertEqual(second["pending"], 1)
            self.assertEqual(requests, ["1", "2"])
            retried = discovery.run_discovery(database, fetcher=fetch, request_delay=0, clock=lambda: 2801)
            self.assertEqual(retried["status"], "FAILED")
            self.assertEqual(requests[-1], "2")

    def test_failure_and_malformed_responses_do_not_advance_cursor_or_look_successful(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            result = discovery.run_discovery(database, fetcher=lambda _: b"<html>Access denied</html>", request_delay=0)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["queued"], 0)
            self.assertEqual(result["nextPages"], {})
            self.assertEqual(len(result["failures"]), len(discovery.SOURCES))

    def test_repeated_final_page_is_bounded_and_restarts_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            result = discovery.run_discovery(Path(directory) / "catalog.db", fetcher=lambda _: self.html("10", "Game"),
                                             request_delay=0, pages_per_source=10)
            self.assertEqual(result["pagesFetched"], len(discovery.SOURCES) * 2)
            self.assertEqual(set(result["nextPages"].values()), {1})


if __name__ == "__main__":
    unittest.main()
