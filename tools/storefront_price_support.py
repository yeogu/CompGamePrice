#!/usr/bin/env python3
"""Shared bounded-retry and atomic snapshot support for storefront collectors."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError


class PermanentCollectionError(ValueError):
    pass


class TransientCollectionError(RuntimeError):
    pass


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
) -> tuple[list[str], list[tuple[str, str]]]:
    if max_attempts < 1:
        raise ValueError("max attempts must be positive")
    if retry_delay < 0 or request_delay < 0:
        raise ValueError("collection delays cannot be negative")
    rows: list[str] = []
    failures: list[tuple[str, str]] = []
    for index, (product_id, game_id, product_url) in enumerate(targets):
        if index > 0 and request_delay > 0:
            sleeper(request_delay)
        last_error = ""
        succeeded = False
        for attempt in range(max_attempts):
            try:
                raw = fetcher(product_id, game_id, product_url, timeout)
                rows.append(normalizer(raw, product_id, game_id, product_url))
                succeeded = True
                break
            except PermanentCollectionError as error:
                last_error = str(error)
                break
            except HTTPError as error:
                last_error = f"HTTP {error.code}"
                if error.code not in {408, 429} and error.code < 500:
                    break
            except (TimeoutError, URLError) as error:
                last_error = str(error)
            except Exception as error:
                last_error = str(error)
            if attempt + 1 < max_attempts and retry_delay > 0:
                sleeper(retry_delay * (2**attempt))
        if not succeeded:
            failures.append((product_id, last_error))
    return rows, failures
