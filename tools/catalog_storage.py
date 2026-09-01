"""Safe, serialized updates for the JSON game catalog."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile


class CatalogStorageError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def catalog_hash(document: dict) -> str:
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_catalog(document: dict) -> None:
    games = document.get("games")
    if document.get("schemaVersion") != 4 or not isinstance(games, list):
        raise CatalogStorageError("Game catalog requires schemaVersion 4 and games")
    game_ids = set()
    product_ids = set()
    for game in games:
        if not isinstance(game, dict):
            raise CatalogStorageError("Game catalog contains an invalid game")
        game_id = game.get("id")
        title = game.get("title")
        if not isinstance(game_id, str) or not game_id:
            raise CatalogStorageError("Game catalog contains an invalid game id")
        if re.search(r"[a-z]", game_id) is None:
            raise CatalogStorageError(
                f"Canonical game id must contain a letter: {game_id}"
            )
        if game_id in game_ids:
            raise CatalogStorageError(f"Duplicate canonical game id: {game_id}")
        if not isinstance(title, str) or not title.strip():
            raise CatalogStorageError(f"Game has no title: {game_id}")
        game_ids.add(game_id)
        for product in game.get("products", []):
            if not isinstance(product, dict):
                raise CatalogStorageError(f"Game has an invalid Store product: {game_id}")
            store = product.get("store")
            product_id = product.get("productId")
            if not isinstance(store, str) or not store:
                raise CatalogStorageError(f"Store product has no Store: {game_id}")
            if not isinstance(product_id, str) or not product_id:
                raise CatalogStorageError(f"Store product has no product id: {game_id}")
            identity = (store, product_id)
            if identity in product_ids:
                raise CatalogStorageError(
                    f"Duplicate Store product id in Game Catalog: {product_id}"
                )
            product_ids.add(identity)


def find_product_game(document: dict, store: str, product_id: str) -> dict | None:
    for game in document["games"]:
        if any(
            product.get("store") == store and
            product.get("productId") == product_id
            for product in game.get("products", [])
        ):
            return game
    return None


@contextmanager
def catalog_lock(catalog_path: Path):
    lock_path = catalog_path.with_suffix(catalog_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def encoded_catalog(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def initialize_audit(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_change_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK(outcome IN ('PENDING','APPLIED','NO_OP')),
            before_hash TEXT NOT NULL,
            after_hash TEXT,
            occurred_at TEXT NOT NULL,
            detail TEXT
        )
        """
    )


def begin_audit(
    connection: sqlite3.Connection,
    actor: str,
    action: str,
    store: str,
    product_id: str,
    game_id: str,
    before_hash: str,
) -> int:
    initialize_audit(connection)
    cursor = connection.execute(
        """
        INSERT INTO catalog_change_audit(
            actor, action, store, external_product_id, game_id,
            outcome, before_hash, occurred_at
        ) VALUES(?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """,
        (actor, action, store, product_id, game_id, before_hash, utc_now()),
    )
    return cursor.lastrowid


def finish_audit(
    connection: sqlite3.Connection,
    audit_id: int,
    outcome: str,
    after_hash: str,
    detail: str | None,
) -> None:
    connection.execute(
        """
        UPDATE catalog_change_audit
        SET outcome = ?, after_hash = ?, detail = ?
        WHERE id = ?
        """,
        (outcome, after_hash, detail, audit_id),
    )


def update_catalog(
    catalog_path: Path,
    updater,
    *,
    store: str,
    product_id: str,
    game_id: str,
    database_path: Path | None = None,
    actor: str = "catalog-admin",
    action: str = "CONNECT_STORE_PRODUCT",
    detail: str | None = None,
) -> tuple[dict, bool]:
    with catalog_lock(catalog_path):
        original_bytes = catalog_path.read_bytes()
        current = json.loads(original_bytes)
        validate_catalog(current)
        updated, result = updater(current)
        validate_catalog(updated)
        changed = updated != current
        before_hash = catalog_hash(current)
        after_hash = catalog_hash(updated)
        connection = sqlite3.connect(database_path) if database_path else None
        audit_id = None
        try:
            if connection is not None:
                connection.execute("BEGIN IMMEDIATE")
                audit_id = begin_audit(
                    connection,
                    actor,
                    action,
                    store,
                    product_id,
                    game_id,
                    before_hash,
                )
            if changed:
                backup = catalog_path.with_suffix(catalog_path.suffix + ".bak")
                shutil.copy2(catalog_path, backup)
                atomic_write(catalog_path, encoded_catalog(updated))
            if connection is not None and audit_id is not None:
                finish_audit(
                    connection,
                    audit_id,
                    "APPLIED" if changed else "NO_OP",
                    after_hash,
                    detail if changed else "Catalog already contained the requested state",
                )
                connection.commit()
        except Exception:
            if changed:
                atomic_write(catalog_path, original_bytes)
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
        return result, changed
