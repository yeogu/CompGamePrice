import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "ecb_rates", ROOT / "tools" / "sync_ecb_exchange_rates.py"
)
ecb_rates = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ecb_rates)


class EcbExchangeRateTest(unittest.TestCase):
    def test_parses_cross_rates_and_persists_them(self):
        document = b'''<Envelope><Cube><Cube time="2026-09-11">
          <Cube currency="USD" rate="1.1592"/>
          <Cube currency="GBP" rate="0.85815"/>
          <Cube currency="JPY" rate="178.56"/>
          <Cube currency="KRW" rate="1556.56"/>
        </Cube></Cube></Envelope>'''
        rows = ecb_rates.parse(document)
        usd = next(rate for date, currency, rate in rows if currency == "USD")
        self.assertAlmostEqual(usd, 1556.56 / 1.1592)

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prices.db"
            self.assertEqual(ecb_rates.save(database, rows), 4)
            connection = sqlite3.connect(database)
            saved = connection.execute(
                "SELECT rate, source FROM exchange_rates "
                "WHERE rate_date='2026-09-11' AND base_currency='USD'"
            ).fetchone()
            connection.close()
            self.assertAlmostEqual(saved[0], usd)
            self.assertEqual(saved[1], "ECB")


if __name__ == "__main__":
    unittest.main()
