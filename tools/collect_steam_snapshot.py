#!/usr/bin/env python3
"""Fetch Steam Storefront responses and create local Provider snapshots."""

from __future__ import annotations

import argparse
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
    return row


def write_products_snapshot(output_directory: Path, rows: list[str]) -> None:
    atomic_write(
        output_directory / "steam_products.txt",
        (
            "# app_id|canonical_game_id|final_price_krw|platform_flags|available|observed_at\n"
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
) -> None:
    row = write_raw_snapshot(
        raw, output_directory, app_id, game_id, source_url, http_status
    )
    write_products_snapshot(output_directory, [row])


def load_targets(path: Path) -> list[tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_targets = payload.get("targets") if isinstance(payload, dict) else None
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("Steam targets must contain a non-empty targets list")

    targets: list[tuple[str, str]] = []
    seen_app_ids: set[str] = set()
    for target in raw_targets:
        if not isinstance(target, dict):
            raise ValueError("Each Steam target must be an object")
        app_id = str(target.get("appId", ""))
        game_id = target.get("gameId")
        if not app_id.isdigit() or not isinstance(game_id, str) or not game_id:
            raise ValueError("Each Steam target requires numeric appId and gameId")
        if app_id in seen_app_ids:
            raise ValueError(f"Duplicate Steam appId: {app_id}")
        seen_app_ids.add(app_id)
        targets.append((app_id, game_id))
    return targets


def load_catalog_game_ids(path: Path) -> set[str]:
    game_ids: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) != 2 or not fields[0] or not fields[1]:
            raise ValueError(f"Invalid game catalog row at line {line_number}")
        if fields[0] in game_ids:
            raise ValueError(f"Duplicate canonical game id: {fields[0]}")
        game_ids.add(fields[0])
    if not game_ids:
        raise ValueError("Game catalog must contain at least one game")
    return game_ids


def validate_targets_in_catalog(
    targets: list[tuple[str, str]], catalog_game_ids: set[str]
) -> None:
    unknown = sorted({game_id for _app_id, game_id in targets} - catalog_game_ids)
    if unknown:
        raise ValueError(
            "Steam targets reference unknown canonical game ids: " + ", ".join(unknown)
        )


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
                        raw, output_directory, app_id, game_id, source_url, status
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
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--targets", type=Path, help="JSON file containing Steam targets.")
    parser.add_argument("--request-delay", default=1.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    parser.add_argument("--retry-delay", default=1.0, type=float)
    parser.add_argument(
        "--input",
        type=Path,
        help="Read a saved response instead of using the network (for tests).",
    )
    arguments = parser.parse_args()

    if arguments.targets and arguments.input:
        parser.error("--targets and --input cannot be used together")

    if arguments.targets:
        targets = load_targets(arguments.targets)
        success_count, failures = collect_targets(
            targets,
            arguments.output_dir,
            arguments.country,
            arguments.language,
            arguments.timeout,
            arguments.request_delay,
            arguments.max_attempts,
            arguments.retry_delay,
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
    )
    print(f"Steam snapshot saved to {arguments.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
