#!/usr/bin/env python3
"""Store ECB daily reference rates converted to KRW cross rates."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import collect_steam_snapshot as network_support


SOURCE_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
SUPPORTED = {"USD", "EUR", "GBP", "JPY"}


def fetch(timeout: float = 30.0) -> bytes:
    request = Request(SOURCE_URL, headers={"User-Agent": "DealQuest/1.0"})
    with urlopen(
        request,
        timeout=timeout,
        context=network_support.tls_context(),
    ) as response:
        return response.read()


def parse(document: bytes) -> list[tuple[str, str, float]]:
    root = ET.fromstring(document)
    rows: list[tuple[str, str, float]] = []
    for day in root.iter():
        rate_date = day.attrib.get("time")
        if not rate_date:
            continue
        euro_rates = {
            item.attrib.get("currency", ""): float(item.attrib["rate"])
            for item in day
            if item.attrib.get("currency") and item.attrib.get("rate")
        }
        krw_per_eur = euro_rates.get("KRW")
        if not krw_per_eur:
            continue
        rows.append((rate_date, "EUR", krw_per_eur))
        for currency in SUPPORTED - {"EUR"}:
            units_per_eur = euro_rates.get(currency)
            if units_per_eur:
                rows.append((rate_date, currency, krw_per_eur / units_per_eur))
    return rows


def save(database: Path, rows: list[tuple[str, str, float]]) -> int:
    connection = sqlite3.connect(database, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exchange_rates (
                rate_date TEXT NOT NULL,
                base_currency TEXT NOT NULL,
                quote_currency TEXT NOT NULL DEFAULT 'KRW',
                rate REAL NOT NULL CHECK(rate > 0),
                source TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(rate_date, base_currency, quote_currency)
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO exchange_rates(
                rate_date, base_currency, quote_currency, rate, source)
            VALUES(?, ?, 'KRW', ?, 'ECB')
            ON CONFLICT(rate_date, base_currency, quote_currency) DO UPDATE SET
                rate=excluded.rate,
                source=excluded.source,
                fetched_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            rows,
        )
        connection.commit()
        return len(rows)
    finally:
        connection.close()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=root / "build/game_prices.db",
        type=Path,
    )
    args = parser.parse_args()
    rows = parse(fetch())
    if not rows:
        raise SystemExit("ECB response contained no supported exchange rates")
    print(f"Stored {save(args.database, rows)} ECB exchange rates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
