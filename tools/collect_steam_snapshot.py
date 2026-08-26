#!/usr/bin/env python3
"""Fetch Steam Storefront responses and create local Provider snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
import time
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
    raw_initial = price.get("initial")
    raw_final = price.get("final")
    discount_percent = price.get("discount_percent")
    if (
        not isinstance(raw_initial, int)
        or not isinstance(raw_final, int)
        or raw_initial < raw_final
        or raw_final < 0
        or raw_initial % 100 != 0
        or raw_final % 100 != 0
    ):
        raise ValueError("Steam KRW prices have an unexpected representation")
    if (
        not isinstance(discount_percent, int)
        or not 0 <= discount_percent <= 100
    ):
        raise ValueError("Steam discount percent has an unexpected representation")
    initial_price_won = raw_initial // 100
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

    return (
        f"{app_id}|{game_id}|{initial_price_won}|{final_price_won}|"
        f"{discount_percent}|{','.join(platforms)}|true\n"
    )


def collected_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def write_raw_snapshot(
    raw: bytes,
    output_directory: Path,
    app_id: str,
    game_id: str,
    source_url: str,
    http_status: int | None,
    archive_directory: Path | None = None,
) -> str:
    observation_time = collected_at()
    row = normalized_row(raw, app_id, game_id).rstrip("\n")
    row = f"{row}|{observation_time}\n"
    metadata = {
        "store": "Steam",
        "appId": app_id,
        "gameId": game_id,
        "collectedAt": observation_time,
        "sourceUrl": source_url,
        "httpStatus": http_status,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }

    atomic_write(output_directory / f"steam_{app_id}.json", raw)
    atomic_write(
        output_directory / f"steam_{app_id}.metadata.json",
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    if archive_directory is not None:
        archive_name = observation_time.replace("-", "").replace(":", "").replace(".", "")
        app_archive = archive_directory / app_id
        atomic_write(
            app_archive / f"{archive_name}.json.gz",
            gzip.compress(raw, mtime=0),
        )
        atomic_write(
            app_archive / f"{archive_name}.metadata.json",
            (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    return row


def write_products_snapshot(output_directory: Path, rows: list[str]) -> None:
    atomic_write(
        output_directory / "steam_products.txt",
        (
            "# app_id|canonical_game_id|regular_price_krw|final_price_krw|"
            "discount_percent|platform_flags|available|observed_at\n"
            + "".join(rows)
        ).encode("utf-8"),
    )


def write_snapshot(
    raw: bytes,
    output_directory: Path,
    app_id: str,
    game_id: str,
    source_url: str,
    http_status: int | None,
    archive_directory: Path | None = None,
) -> None:
    row = write_raw_snapshot(
        raw, output_directory, app_id, game_id, source_url, http_status,
        archive_directory,
    )
    write_products_snapshot(output_directory, [row])


def load_steam_targets(path: Path) -> list[tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("Game catalog requires schemaVersion 1")
    games = payload.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("Game catalog must contain a non-empty games list")

    targets: list[tuple[str, str]] = []
    seen_game_ids: set[str] = set()
    seen_titles: set[str] = set()
    seen_app_ids: set[str] = set()
    for game in games:
        if not isinstance(game, dict):
            raise ValueError("Each catalog game must be an object")
        game_id = game.get("id")
        title = game.get("title")
        if not isinstance(game_id, str) or not game_id.strip():
            raise ValueError("Each catalog game requires a non-empty id")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Catalog game {game_id} requires a non-empty title")
        normalized_title = " ".join(title.lower().split())
        if game_id in seen_game_ids:
            raise ValueError(f"Duplicate canonical game id: {game_id}")
        if normalized_title in seen_titles:
            raise ValueError(f"Duplicate canonical game title: {title}")
        seen_game_ids.add(game_id)
        seen_titles.add(normalized_title)

        stores = game.get("stores")
        if not isinstance(stores, dict):
            raise ValueError(f"Catalog game {game_id} requires stores")
        steam = stores.get("steam")
        if steam is None:
            continue
        if not isinstance(steam, dict):
            raise ValueError(f"Steam mapping for {game_id} must be an object")
        app_id = steam.get("productId")
        if not isinstance(app_id, str) or not app_id.isdigit():
            raise ValueError(f"Steam mapping for {game_id} requires numeric productId")
        if app_id in seen_app_ids:
            raise ValueError(f"Duplicate Steam productId: {app_id}")
        seen_app_ids.add(app_id)
        targets.append((app_id, game_id))
    if not targets:
        raise ValueError("Game catalog contains no Steam products")
    return targets


def write_failure(
    output_directory: Path,
    app_id: str,
    game_id: str,
    attempts: int,
    error: Exception,
) -> None:
    metadata = {
        "store": "Steam",
        "appId": app_id,
        "gameId": game_id,
        "collectedAt": collected_at(),
        "attempts": attempts,
        "error": str(error),
    }
    atomic_write(
        output_directory / f"steam_{app_id}.error.json",
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def collect_targets(
    targets: list[tuple[str, str]],
    output_directory: Path,
    country: str,
    language: str,
    timeout: float,
    request_delay: float,
    max_attempts: int,
    retry_delay: float,
    fetcher=fetch,
    sleeper=time.sleep,
    archive_directory: Path | None = None,
) -> tuple[int, list[tuple[str, str]]]:
    if request_delay < 0 or retry_delay < 0 or max_attempts < 1:
        raise ValueError("Delays must be non-negative and max attempts must be positive")

    rows: list[str] = []
    failures: list[tuple[str, str]] = []
    for target_index, (app_id, game_id) in enumerate(targets):
        if target_index > 0 and request_delay > 0:
            sleeper(request_delay)

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                raw, status, source_url = fetcher(
                    app_id, country, language, timeout
                )
                rows.append(
                    write_raw_snapshot(
                        raw, output_directory, app_id, game_id, source_url, status,
                        archive_directory,
                    )
                )
                last_error = None
                break
            except Exception as error:
                last_error = error
                if attempt < max_attempts and retry_delay > 0:
                    sleeper(retry_delay * (2 ** (attempt - 1)))

        if last_error is not None:
            write_failure(output_directory, app_id, game_id, max_attempts, last_error)
            failures.append((app_id, str(last_error)))

    if rows:
        write_products_snapshot(output_directory, rows)
    return len(rows), failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", default="413150")
    parser.add_argument("--game-id", default="stardew-valley")
    parser.add_argument("--country", default="kr")
    parser.add_argument("--language", default="korean")
    parser.add_argument("--output-dir", default="snapshots/latest", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--catalog", type=Path, help="Unified JSON game catalog.")
    parser.add_argument("--request-delay", default=1.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
    parser.add_argument(
        "--input",
        type=Path,
        help="Read a saved response instead of using the network (for tests).",
    )
    arguments = parser.parse_args()

    if arguments.catalog and arguments.input:
        parser.error("--catalog and --input cannot be used together")

    if arguments.catalog:
        targets = load_steam_targets(arguments.catalog)
        success_count, failures = collect_targets(
            targets,
            arguments.output_dir,
            arguments.country,
            arguments.language,
            arguments.timeout,
            arguments.request_delay,
            arguments.max_attempts,
            arguments.retry_delay,
            archive_directory=arguments.archive_dir,
        )
        print(
            f"Steam snapshot saved to {arguments.output_dir}: "
            f"{success_count} succeeded, {len(failures)} failed"
        )
        for app_id, error in failures:
            print(f"- app {app_id}: {error}")
        return 1 if failures else 0

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
        arguments.archive_dir,
    )
    print(f"Steam snapshot saved to {arguments.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
