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
        "platforms": ["iOS"],
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

    def test_approved_google_candidate_is_connected_without_manual_review(self):
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
        self.assertEqual(report["autoConnected"], 1)
        updated = json.loads(self.catalog.read_text(encoding="utf-8"))
        self.assertEqual(
            updated["games"][0]["products"][0]["store"],
            "GooglePlay",
        )
        status = sync.synchronization_status(self.database, "GooglePlay")
        self.assertEqual(status["pendingReviews"], [])

    def test_approved_apple_candidate_is_connected_with_device_platforms(self):
        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "AppleAppStore",
            10,
            searcher=lambda query, limit, timeout: [
                {"externalProductId": "1406710800", "title": query}
            ],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=approved_metadata,
        )

        self.assertEqual(report["autoConnected"], 1)
        game = json.loads(self.catalog.read_text(encoding="utf-8"))["games"][0]
        self.assertIn("iOS", game["platforms"])
        self.assertEqual(game["products"][0]["store"], "AppleAppStore")

    def test_explicit_free_mobile_game_is_connected(self):
        def free_metadata(raw, product_id):
            result = approved_metadata(raw, product_id)
            result["priceMinor"] = 0
            return result

        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "GooglePlay",
            10,
            searcher=lambda query, limit, timeout: [{
                "externalProductId": "com.example.freegame",
                "title": query,
            }],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=free_metadata,
        )

        self.assertEqual(report["autoConnected"], 1)

    def test_unknown_mobile_price_requires_manual_review(self):
        def unknown_price_metadata(raw, product_id):
            result = approved_metadata(raw, product_id)
            result["priceMinor"] = None
            result["currency"] = ""
            return result

        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "AppleAppStore",
            10,
            searcher=lambda query, limit, timeout: [{
                "externalProductId": "100",
                "title": query,
            }],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=unknown_price_metadata,
        )

        self.assertEqual(report["autoConnected"], 0)
        self.assertEqual(report["needsReview"], 1)

    def test_approved_nintendo_candidate_is_connected_to_korean_eshop(self):
        def nintendo_metadata(raw, product_id):
            del raw
            return {
                **approved_metadata(b"", product_id),
                "productId": product_id,
                "platforms": ["NintendoSwitch"],
            }

        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "NintendoEShop",
            10,
            searcher=lambda query, limit, timeout: [{
                "externalProductId": "70010000033128",
                "title": query,
                "productUrl": "https://store.nintendo.co.kr/70010000033128",
            }],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=nintendo_metadata,
        )

        self.assertEqual(report["autoConnected"], 1)
        game = json.loads(self.catalog.read_text(encoding="utf-8"))["games"][0]
        self.assertIn("NintendoSwitch", game["platforms"])
        self.assertEqual(game["products"][0]["store"], "NintendoEShop")
        self.assertEqual(
            game["products"][0]["productUrl"],
            "https://store.nintendo.co.kr/70010000033128",
        )

    def test_uncertain_candidate_remains_in_manual_review(self):
        def incomplete_metadata(raw, product_id):
            result = approved_metadata(raw, product_id)
            result["developer"] = ""
            return result

        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "GooglePlay",
            10,
            searcher=lambda query, limit, timeout: [
                {"externalProductId": "com.example.stardew", "title": query}
            ],
            fetcher=lambda product_id, timeout: b"product",
            metadata_parser=incomplete_metadata,
        )

        self.assertEqual(report["needsReview"], 1)
        unchanged = json.loads(self.catalog.read_text(encoding="utf-8"))
        self.assertEqual(unchanged["games"][0]["products"], [])
        status = sync.synchronization_status(self.database, "GooglePlay")
        self.assertEqual(status["pendingReviews"][0]["decision"], "NeedsReview")
        reasons = status["recentRuns"][0]["reasonCounts"]
        self.assertEqual(
            reasons["Developer and publisher information is incomplete"],
            1,
        )

    def test_no_search_result_is_reported_as_a_rejection_reason(self):
        report = sync.synchronize_provider(
            self.catalog,
            self.database,
            "GooglePlay",
            10,
            searcher=lambda query, limit, timeout: [],
        )

        self.assertEqual(report["rejected"], 1)
        self.assertEqual(report["reasonCounts"]["No Store search results"], 1)
        status = sync.synchronization_status(self.database, "GooglePlay")
        self.assertEqual(
            status["recentRuns"][0]["exclusions"][0]["gameId"],
            "stardew-valley",
        )
        self.assertEqual(
            status["recentRuns"][0]["reasonCounts"]["No Store search results"],
            1,
        )

    def test_rechecks_old_rejection_but_not_recent_rejection(self):
        with sqlite3.connect(self.database) as connection:
            sync.initialize_state(connection)
            connection.execute(
                """
                INSERT INTO catalog_sync_seen(
                    provider, external_product_id, outcome, checked_at
                ) VALUES('GooglePlay:game', 'stardew-valley', 'NO_MATCH', ?)
                """,
                ("2020-01-01T00:00:00Z",),
            )
            connection.commit()
            old_rejection = sync.pending_games(
                connection,
                catalog_document(),
                "GooglePlay",
                10,
            )
            connection.execute(
                """
                UPDATE catalog_sync_seen
                SET checked_at = ?
                WHERE provider = 'GooglePlay:game'
                """,
                (sync.utc_now(),),
            )
            recent_rejection = sync.pending_games(
                connection,
                catalog_document(),
                "GooglePlay",
                10,
            )

        self.assertEqual([game["id"] for game in old_rejection], ["stardew-valley"])
        self.assertEqual(recent_rejection, [])

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
        self.assertEqual(count, 0)
        with sqlite3.connect(self.database) as connection:
            audits = connection.execute(
                "SELECT action, outcome FROM catalog_change_audit"
            ).fetchall()
        self.assertEqual(
            audits,
            [("AUTO_CONNECT_STORE_PRODUCT", "APPLIED")],
        )

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
        self.assertEqual(status["pendingReviews"], [])
        game = json.loads(self.catalog.read_text(encoding="utf-8"))["games"][0]
        self.assertEqual(game["products"][0]["productId"], "correct.product")

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
        status = sync.synchronization_status(self.database, "GooglePlay")
        failures = status["recentRuns"][0]["failures"]
        self.assertEqual(failures[0]["gameId"], "stardew-valley")
        self.assertEqual(failures[0]["title"], "Stardew Valley")
        self.assertEqual(failures[0]["reason"], "malformed response")


if __name__ == "__main__":
    unittest.main()
