"""Download and score game artwork for catalog selection."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import sys
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ImageQuality:
    width: int
    height: int
    edge_whitespace: float
    score: float

    def reasons(self) -> list[str]:
        result = []
        ratio = self.width / self.height
        if self.width < 640 or self.height < 360:
            result.append("LOW_RESOLUTION")
        if ratio < 1.35:
            result.append("NOT_LANDSCAPE")
        if self.edge_whitespace >= 0.5:
            result.append("SOLID_EDGE_WHITESPACE")
        if self.score < 65:
            result.append("LOW_SCORE")
        return result

    def to_json(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "aspectRatio": round(self.width / self.height, 3),
            "edgeWhitespace": round(self.edge_whitespace, 3),
            "score": round(self.score, 1),
            "quality": "GOOD" if self.score >= 65 else "LOW",
            "reasons": self.reasons(),
        }


def score_metrics(width: int, height: int, edge_whitespace: float) -> float:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions are invalid")
    ratio = width / height
    resolution_score = min(25.0, (width * height) / 8_000)
    ratio_score = max(0.0, 45.0 - abs(ratio - (16 / 9)) * 24.0)
    landscape_bonus = 15.0 if ratio >= 1.35 else 0.0
    whitespace_penalty = edge_whitespace * 55.0
    return resolution_score + ratio_score + landscape_bonus - whitespace_penalty


def fetch_bytes(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "DealQuest/0.1 artwork-quality"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(8 * 1024 * 1024)


def uniform_edge_ratio(image) -> float:
    from PIL import ImageStat

    sample = image.convert("RGB")
    sample.thumbnail((96, 96))
    width, height = sample.size
    band_width = max(1, width // 12)
    band_height = max(1, height // 12)
    bands = (
        sample.crop((0, 0, width, band_height)),
        sample.crop((0, height - band_height, width, height)),
        sample.crop((0, 0, band_width, height)),
        sample.crop((width - band_width, 0, width, height)),
    )
    uniform = 0
    for band in bands:
        statistics = ImageStat.Stat(band)
        variation = sum(statistics.stddev) / len(statistics.stddev)
        brightness = sum(statistics.mean) / len(statistics.mean)
        if variation < 8 and (brightness > 225 or brightness < 30):
            uniform += 1
    return uniform / len(bands)


def inspect(url: str, timeout: float = 15.0) -> ImageQuality:
    from PIL import Image

    with Image.open(BytesIO(fetch_bytes(url, timeout))) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("image dimensions are invalid")
        edge_whitespace = uniform_edge_ratio(image)
        score = score_metrics(width, height, edge_whitespace)
        return ImageQuality(width, height, edge_whitespace, score)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: image_quality.py IMAGE_URL", file=sys.stderr)
        return 2
    try:
        result = inspect(sys.argv[1])
        print(json.dumps(result.to_json(), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"quality": "BROKEN", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
