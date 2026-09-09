import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import image_quality


class ImageQualityTest(unittest.TestCase):
    def test_prefers_wide_artwork_without_solid_edge_whitespace(self):
        wide_score = image_quality.score_metrics(920, 430, 0.0)
        padded_square_score = image_quality.score_metrics(512, 512, 0.5)

        self.assertGreater(wide_score, padded_square_score)

    def test_rejects_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            image_quality.score_metrics(0, 400, 0.0)


if __name__ == "__main__":
    unittest.main()
