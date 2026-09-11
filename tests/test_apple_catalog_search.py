import importlib.util
import json
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
        document = json.loads(
            (ROOT / "tests/fixtures/apple_search_stardew.json").read_bytes()
        )
        document["results"][0]["artworkUrl512"] = (
            "https://cdn.example.test/stardew-apple.jpg"
        )
        raw = json.dumps(document).encode()
        candidate = search.parse_results(raw)[0]
        self.assertEqual(candidate["externalProductId"], "1406710800")
        self.assertEqual(candidate["developer"], "ConcernedApe")
        self.assertEqual(candidate["platforms"], ["iOS", "iPadOS"])
        self.assertEqual(candidate["priceMinor"], 6600)
        self.assertEqual(
            candidate["imageUrl"],
            "https://cdn.example.test/stardew-apple.jpg",
        )

    def test_excludes_non_game_applications(self):
        document = {
            "resultCount": 2,
            "results": [
                {
                    "trackId": 363590051,
                    "trackName": "Netflix",
                    "primaryGenreId": 6016,
                    "primaryGenreName": "Entertainment",
                },
                {
                    "trackId": 1406710800,
                    "trackName": "Stardew Valley",
                    "primaryGenreId": 6014,
                    "primaryGenreName": "Games",
                },
            ],
        }
        candidates = search.parse_results(json.dumps(document).encode())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "Stardew Valley")

    def test_recognizes_games_genre_id_without_localized_name(self):
        document = {
            "resultCount": 1,
            "results": [
                {
                    "trackId": 1406710800,
                    "trackName": "Stardew Valley",
                    "primaryGenreId": 6014,
                    "primaryGenreName": "Jeux",
                },
            ],
        }
        candidates = search.parse_results(json.dumps(document).encode())
        self.assertEqual(len(candidates), 1)

    def test_omits_null_price_from_candidate(self):
        document = {
            "resultCount": 1,
            "results": [
                {
                    "trackId": 1406710800,
                    "trackName": "Stardew Valley",
                    "primaryGenreId": 6014,
                    "price": None,
                },
            ],
        }
        candidate = search.parse_results(json.dumps(document).encode())[0]
        self.assertNotIn("priceMinor", candidate)


if __name__ == "__main__":
    unittest.main()
