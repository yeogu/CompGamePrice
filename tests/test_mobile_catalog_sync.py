import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "mobile_catalog_sync",
    ROOT / "tools" / "sync_mobile_catalog.py",
)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync)


def catalog_document() -> dict:
    return {
        "schemaVersion": 4,
        "games": [
            {
                "id": "stardew-valley",
                "title": "Stardew Valley",
                "aliases": ["스타듀 밸리"],
                "developers": ["ConcernedApe"],
                "publishers": ["ConcernedApe"],
                "platforms": ["Windows"],
                "genres": ["Simulation"],
                "products": [],
            }
        ],
    }


def approved_metadata(raw: bytes, product_id: str) -> dict:
    del raw
    del product_id
    return {
        "title": "Stardew Valley",
        "developer": "ConcernedApe",
        "priceMinor": 6600,
        "currency": "KRW",
        "isGame": True,
        "supportsTargetPlatform": True,
        "excludedWords": [],
    }


class MobileCatalogSyncTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.catalog = self.directory / "catalog.json"
        self.database = self.directory / "prices.db"
        self.catalog.write_text(
            json.dumps(catalog_document(), ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_approved_candidate_is_queued_without_catalog_registration(self):
        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "GooglePlay",
            10,
            searcher=lambda query, limit, timeout: [
                {
                    "externalProductId": "com.chucklefish.stardewvalley",
                    "title": query,
                    "productUrl": "https://example.test/google",
                }
            ],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=approved_metadata,
        )

        self.assertEqual(report["approvedCandidates"], 1)
        unchanged = json.loads(self.catalog.read_text(encoding="utf-8"))
        self.assertEqual(unchanged["games"][0]["products"], [])
        status = sync.synchronization_status(self.database, "GooglePlay")
        self.assertEqual(status["pendingReviews"][0]["gameId"], "stardew-valley")
        self.assertEqual(status["pendingReviews"][0]["decision"], "ApprovedCandidate")

    def test_rerun_does_not_duplicate_processed_game(self):
        arguments = {
            "searcher": lambda query, limit, timeout: [
                {"externalProductId": "123", "title": query}
            ],
            "fetcher": lambda product_id, timeout: b"product",
            "metadata_parser": approved_metadata,
        }
        first = sync.synchronize_provider(
            self.catalog,
            self.database,
            "AppleAppStore",
            10,
            **arguments,
        )
        second = sync.synchronize_provider(
            self.catalog,
            self.database,
            "AppleAppStore",
            10,
            **arguments,
        )

        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["processed"], 0)
        with sqlite3.connect(self.database) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM catalog_sync_review WHERE provider = 'AppleAppStore'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_retry_is_bounded_and_recorded(self):
        attempts = []

        def flaky_search(query, limit, timeout):
            attempts.append(query)
            if len(attempts) < 3:
                raise TimeoutError("temporary timeout")
            return [{"externalProductId": "123", "title": query}]

        original_sleep = sync.time.sleep
        sync.time.sleep = lambda delay: None
        try:
            report = sync.synchronize_provider(
                self.catalog,
                self.database,
                "AppleAppStore",
                10,
                max_attempts=3,
                searcher=flaky_search,
                fetcher=lambda product_id, timeout: b"product",
                metadata_parser=approved_metadata,
            )
        finally:
            sync.time.sleep = original_sleep

        self.assertEqual(len(attempts), 3)
        self.assertEqual(report["retries"], 2)
        status = sync.synchronization_status(self.database, "AppleAppStore")
        self.assertEqual(status["recentRuns"][0]["retries"], 2)

    def test_prefers_verified_match_over_first_search_result(self):
        def metadata(raw, product_id):
            result = approved_metadata(raw, product_id)
            if product_id == "wrong.product":
                result["title"] = "Stardew Valley Guide"
                result["excludedWords"] = ["guide"]
            return result

        sync.synchronize_provider(
            self.catalog,
            self.database,
            "GooglePlay",
            10,
            searcher=lambda query, limit, timeout: [
                {"externalProductId": "wrong.product", "title": "Guide"},
                {"externalProductId": "correct.product", "title": query},
            ],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=metadata,
        )

        status = sync.synchronization_status(self.database, "GooglePlay")
        self.assertEqual(
            status["pendingReviews"][0]["externalProductId"],
            "correct.product",
        )
        self.assertEqual(status["pendingReviews"][0]["decision"], "ApprovedCandidate")

    def test_one_game_failure_does_not_abort_next_game(self):
        document = catalog_document()
        document["games"].append(
            {
                **document["games"][0],
                "id": "second-game",
                "title": "Second Game",
            }
        )
        self.catalog.write_text(json.dumps(document), encoding="utf-8")

        def search(query, limit, timeout):
            if query == "Stardew Valley":
                raise ValueError("malformed response")
            return [{"externalProductId": "second.product", "title": query}]

        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "GooglePlay",
            10,
            searcher=search,
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=lambda raw, product_id: {
                **approved_metadata(raw, product_id),
                "title": "Second Game",
            },
        )

        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["approvedCandidates"], 1)


if __name__ == "__main__":
    unittest.main()
