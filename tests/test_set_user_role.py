import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "set_user_role",
    ROOT / "tools" / "set_user_role.py",
)
roles = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(roles)


class SetUserRoleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "accounts.db"
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE users(email TEXT UNIQUE COLLATE NOCASE, role TEXT NOT NULL DEFAULT 'USER')"
            )
            connection.execute(
                "INSERT INTO users(email) VALUES('admin@example.com')"
            )

    def tearDown(self):
        self.temporary.cleanup()

    def test_promotes_existing_user(self):
        result = roles.set_user_role(
            self.database,
            "ADMIN@EXAMPLE.COM",
            "ADMIN",
        )

        self.assertEqual(result["role"], "ADMIN")
        with sqlite3.connect(self.database) as connection:
            role = connection.execute(
                "SELECT role FROM users WHERE email = 'admin@example.com'"
            ).fetchone()[0]
        self.assertEqual(role, "ADMIN")

    def test_rejects_unknown_user(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            roles.set_user_role(
                self.database,
                "missing@example.com",
                "ADMIN",
            )


if __name__ == "__main__":
    unittest.main()
