"""Download and score game artwork for catalog selection."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ImageQuality:
    width: int
    height: int
    edge_whitespace: float
    score: float


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
