#!/usr/bin/env python3
"""Fetch one Steam Storefront response and create a local Provider snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "CompGamePricePrototype/0.1 (local development)"
ENDPOINT = "https://store.steampowered.com/api/appdetails"


def tls_context() -> ssl.SSLContext:
    paths = ssl.get_default_verify_paths()
    if paths.cafile and Path(paths.cafile).is_file():
        return ssl.create_default_context()

    for candidate in (
        Path("/etc/ssl/cert.pem"),
        Path("/opt/homebrew/etc/openssl@3/cert.pem"),
        Path("/usr/local/etc/openssl@3/cert.pem"),
    ):
        if candidate.is_file():
            return ssl.create_default_context(cafile=str(candidate))
    raise RuntimeError(
        "No trusted CA bundle was found; install Python certificates or set SSL_CERT_FILE"
    )


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def fetch(app_id: str, country_code: str, language: str, timeout: float) -> tuple[bytes, int, str]:
    query = urlencode({"appids": app_id, "cc": country_code, "l": language})
    source_url = f"{ENDPOINT}?{query}"
    request = Request(source_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=tls_context()) as response:
        return response.read(), response.status, source_url


def normalized_row(raw: bytes, app_id: str, game_id: str) -> str:
    payload = json.loads(raw)
    envelope = payload.get(app_id)
    if not isinstance(envelope, dict) or envelope.get("success") is not True:
        raise ValueError(f"Steam returned no successful data for app {app_id}")

    data = envelope.get("data")
    if not isinstance(data, dict) or data.get("steam_appid") != int(app_id):
        raise ValueError("Steam response contains an unexpected app id")

    price = data.get("price_overview")
    if not isinstance(price, dict) or price.get("currency") != "KRW":
        raise ValueError("Steam response contains no KRW price")
    raw_final = price.get("final")
    if not isinstance(raw_final, int) or raw_final < 0 or raw_final % 100 != 0:
        raise ValueError("Steam KRW final price has an unexpected representation")
    final_price_won = raw_final // 100

    platform_data = data.get("platforms")
    if not isinstance(platform_data, dict):
        raise ValueError("Steam response contains no platform data")
    platforms = [
        name for name in ("windows", "mac", "linux")
        if platform_data.get(name) is True
    ]
    if not platforms:
        raise ValueError("Steam response contains no supported platform")

    return f"{app_id}|{game_id}|{final_price_won}|{','.join(platforms)}|true\n"


def write_snapshot(
    raw: bytes,
    output_directory: Path,
    app_id: str,
    game_id: str,
    source_url: str,
    http_status: int | None,
) -> None:
    row = normalized_row(raw, app_id, game_id)
    collected_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    metadata = {
        "store": "Steam",
        "appId": app_id,
        "gameId": game_id,
        "collectedAt": collected_at,
        "sourceUrl": source_url,
        "httpStatus": http_status,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }

    atomic_write(output_directory / f"steam_{app_id}.json", raw)
    atomic_write(
        output_directory / f"steam_{app_id}.metadata.json",
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    atomic_write(
        output_directory / "steam_products.txt",
        ("# app_id|canonical_game_id|final_price_krw|platform_flags|available\n" + row).encode(
            "utf-8"
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", default="413150")
    parser.add_argument("--game-id", default="stardew-valley")
    parser.add_argument("--country", default="kr")
    parser.add_argument("--language", default="korean")
    parser.add_argument("--output-dir", default="snapshots/latest", type=Path)
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument(
        "--input",
        type=Path,
        help="Read a saved response instead of using the network (for tests).",
    )
    arguments = parser.parse_args()

    if arguments.input:
        raw = arguments.input.read_bytes()
        status = None
        source_url = str(arguments.input)
    else:
        raw, status, source_url = fetch(
            arguments.app_id,
            arguments.country,
            arguments.language,
            arguments.timeout,
        )

    write_snapshot(
        raw,
        arguments.output_dir,
        arguments.app_id,
        arguments.game_id,
        source_url,
        status,
    )
    print(f"Steam snapshot saved to {arguments.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
