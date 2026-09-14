#!/usr/bin/env python3
"""Shared bounded-retry and atomic snapshot support for storefront collectors."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError


class PermanentCollectionError(ValueError):
    pass


class TransientCollectionError(RuntimeError):
    pass


class AdaptiveThrottle:
    """Space requests across workers and temporarily slow everyone after 429."""

    def __init__(self, request_delay: float, max_workers: int):
        self._spacing = request_delay / max(1, max_workers)
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self, sleeper) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_request_at - now)
            self._next_request_at = max(now, self._next_request_at) + self._spacing
        if delay > 0:
            sleeper(delay)

    def penalize(self, seconds: float) -> None:
        with self._lock:
            self._next_request_at = max(
                self._next_request_at,
                time.monotonic() + seconds,
            )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def collect_with_retry(
    targets: list[tuple[str, str, str]],
    normalizer,
    fetcher,
    timeout: float,
    max_attempts: int,
    retry_delay: float,
    request_delay: float,
    sleeper=time.sleep,
    max_workers: int | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    if max_attempts < 1:
        raise ValueError("max attempts must be positive")
    if retry_delay < 0 or request_delay < 0:
        raise ValueError("collection delays cannot be negative")
    selected_workers = max_workers
    if selected_workers is None:
        selected_workers = int(os.getenv("STORE_COLLECTION_MAX_WORKERS", "1"))
    if selected_workers < 1:
        raise ValueError("max workers must be positive")
    selected_workers = min(selected_workers, max(1, len(targets)))
    throttle = AdaptiveThrottle(request_delay, selected_workers)

    def collect_one(
        target: tuple[str, str, str],
    ) -> tuple[str | None, tuple[str, str] | None]:
        product_id, game_id, product_url = target
        last_error = ""
        for attempt in range(max_attempts):
            throttle.wait(sleeper)
            try:
                raw = fetcher(product_id, game_id, product_url, timeout)
                return normalizer(raw, product_id, game_id, product_url), None
            except PermanentCollectionError as error:
                last_error = str(error)
                break
            except HTTPError as error:
                last_error = f"HTTP {error.code}"
                if error.code not in {408, 429} and error.code < 500:
                    break
                if error.code == 429:
                    throttle.penalize(retry_delay * (2**attempt))
            except (TimeoutError, URLError) as error:
                last_error = str(error)
            except Exception as error:
                last_error = str(error)
            if attempt + 1 < max_attempts and retry_delay > 0:
                sleeper(retry_delay * (2**attempt))
        return None, (product_id, last_error)

    with ThreadPoolExecutor(max_workers=selected_workers) as executor:
        results = list(executor.map(collect_one, targets))
    rows = [row for row, _failure in results if row is not None]
    failures = [failure for _row, failure in results if failure is not None]
    return rows, failures
