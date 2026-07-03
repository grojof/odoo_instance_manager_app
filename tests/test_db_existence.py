"""Tests for the best-effort DB existence check used before dropping a database."""

from __future__ import annotations

import shlex
import subprocess
import unittest

from instance_manager.workflows import common
from instance_manager.workflows.common import DbCredentials, _database_exists

CREDS = DbCredentials("127.0.0.1", 5432, "odoo", "pw")


class _FakeRun:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, command: str, check: bool = False):
        self.command = command
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


class DatabaseExistsTests(unittest.TestCase):
    def _patch(self, returncode: int, stdout: str) -> _FakeRun:
        fake = _FakeRun(returncode, stdout)
        self.addCleanup(setattr, common, "run", common.run)
        common.run = fake
        return fake

    def test_true_when_query_returns_one(self) -> None:
        self._patch(0, "1\n")
        self.assertTrue(_database_exists(CREDS, "prod"))

    def test_false_when_absent(self) -> None:
        self._patch(0, "")
        self.assertFalse(_database_exists(CREDS, "missing"))

    def test_false_on_connection_failure(self) -> None:
        self._patch(2, "")
        self.assertFalse(_database_exists(CREDS, "prod"))

    def test_db_name_is_sql_escaped(self) -> None:
        fake = self._patch(0, "")
        _database_exists(CREDS, "o'brien")
        # The single quote is doubled inside the SQL literal (no injection), and the
        # whole SQL is shell-quoted as one argument.
        expected_sql = "SELECT 1 FROM pg_database WHERE datname='o''brien'"
        self.assertIn(shlex.quote(expected_sql), fake.command)


if __name__ == "__main__":
    unittest.main()
