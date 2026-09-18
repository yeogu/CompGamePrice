#!/usr/bin/env python3
"""Shared bounded-retry and atomic snapshot support for storefront collectors."""

from __future__ import annotations

import os
import math
from email.utils import parsedate_to_datetime
from collection_progress import ProgressReporter
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
        self._baseline = self._spacing
        self._successes = 0
        self._penalty_revision = 0
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self, sleeper) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_request_at - now)
            self._next_request_at = max(now, self._next_request_at) + self._spacing
            revision = self._penalty_revision
        if delay > 0:
            sleeper(delay)
        # A different worker may receive Retry-After while this worker sleeps.
        # Re-reserve after a penalty rather than send at the old scheduled time.
        while True:
            with self._lock:
                if revision == self._penalty_revision:
                    return
                now = time.monotonic()
                delay = max(0.0, self._next_request_at - now)
                self._next_request_at = max(now, self._next_request_at) + self._spacing
                revision = self._penalty_revision
            if delay > 0:
                sleeper(delay)

    def penalize(self, seconds: float) -> None:
        with self._lock:
            self._spacing = min(max(30, self._baseline), max(0.1, self._spacing * 2))
            self._successes = 0
            self._penalty_revision += 1
            self._next_request_at = max(
                self._next_request_at,
                time.monotonic() + seconds,
            )

    def succeeded(self) -> None:
        with self._lock:
            self._successes += 1
            if self._successes >= 20:
                self._spacing = max(self._baseline, self._spacing / 2)
                self._successes = 0


def retry_after_seconds(headers, default):
    value = (headers or {}).get("Retry-After")
    if value:
        try:
            seconds = float(value)
            return max(0, seconds) if math.isfinite(seconds) else default
        except ValueError:
            try:
                return max(0, parsedate_to_datetime(value).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                pass
    return default


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
    max_attempts = int(os.getenv("STORE_COLLECTION_MAX_ATTEMPTS", str(max_attempts)))
    if max_attempts < 1:
        raise ValueError("max attempts must be positive")
    if retry_delay < 0 or request_delay < 0:
        raise ValueError("collection delays cannot be negative")
    selected_workers = max_workers
    if selected_workers is None:
        selected_workers = int(os.getenv("STORE_COLLECTION_MAX_WORKERS", "1"))
    if selected_workers < 1:
        raise ValueError("max workers must be positive")
    selected_workers = min(4, selected_workers, max(1, len(targets)))
    throttle = AdaptiveThrottle(request_delay, selected_workers)
    provider_blocked = threading.Event()
    provider_error = []
    progress = ProgressReporter(len(targets))

    def collect_one(
        target: tuple[str, str, str],
    ) -> tuple[str | None, tuple[str, str] | None]:
        product_id, game_id, product_url = target
        last_error = ""
        for attempt in range(max_attempts):
            if provider_blocked.is_set():
                return None, (product_id, provider_error[0])
            throttle.wait(sleeper)
            if provider_blocked.is_set():
                return None, (product_id, provider_error[0])
            retry_pause = retry_delay * (2**attempt)
            try:
                raw = fetcher(product_id, game_id, product_url, timeout)
                row = normalizer(raw, product_id, game_id, product_url)
                throttle.succeeded()
                return row, None
            except PermanentCollectionError as error:
                last_error = str(error)
                break
            except HTTPError as error:
                last_error = f"HTTP {error.code}"
                if error.code in {401, 403}:
                    provider_error.append(last_error + ": provider access denied; remaining requests deferred")
                    provider_blocked.set()
                if error.code not in {408, 429} and error.code < 500:
                    break
                if error.code == 429:
                    pause = retry_after_seconds(error.headers, max(1, retry_pause))
                    if pause > 30 or attempt + 1 >= max_attempts:
                        provider_error.append(f"HTTP 429: provider deferred; retry after {pause:g}s")
                        provider_blocked.set()
                        last_error = provider_error[0]
                        break
                    throttle.penalize(pause)
                    retry_pause = 0  # The shared throttle applies Retry-After.
            except (TimeoutError, URLError) as error:
                last_error = str(error)
            except Exception as error:
                last_error = str(error)
            if attempt + 1 < max_attempts and retry_pause > 0:
                sleeper(retry_pause)
        return None, (product_id, last_error)

    def collect_and_report(target):
        result = collect_one(target)
        progress.completed(result[0] is not None)
        return result

    with ThreadPoolExecutor(max_workers=selected_workers) as executor:
        results = list(executor.map(collect_and_report, targets))
    rows = [row for row, _failure in results if row is not None]
    failures = [failure for _row, failure in results if failure is not None]
    return rows, failures
