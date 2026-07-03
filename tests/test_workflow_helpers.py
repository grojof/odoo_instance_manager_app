"""Tests for pure workflow helpers touched by the data-operation fixes."""

from __future__ import annotations

import unittest

from instance_manager.workflows._core import (
    _db_admin_psql_command,
    _is_safe_path_component,
)


class SafePathComponentTests(unittest.TestCase):
    def test_rejects_traversal_and_separators(self) -> None:
        for name in ["", ".", "..", "a/b", "a\\b", ".hidden", "x\x00y"]:
            with self.subTest(name=name):
                self.assertFalse(_is_safe_path_component(name))

    def test_accepts_plain_db_names(self) -> None:
        for name in ["acme", "acme_2024", "acme2", "odoo18"]:
            with self.subTest(name=name):
                self.assertTrue(_is_safe_path_component(name))


class DbAdminPsqlCommandTests(unittest.TestCase):
    local = ("local", "127.0.0.1", 5432, "", "")
    remote = ("remote", "db.example", 5432, "postgres", "se-cret")

    def test_flags_inserted_before_c_local(self) -> None:
        cmd = _db_admin_psql_command(self.local, "SELECT 1;", psql_flags="-tA")
        self.assertIn("-tA -c", cmd)
        # Exactly one -c flag (no accidental duplication / mangling).
        self.assertEqual(cmd.count(" -c "), 1)

    def test_flags_inserted_before_c_remote_with_dash_c_in_password(self) -> None:
        # The previous .replace("-c", "-tA -c", 1) could corrupt a password
        # containing "-c"; the flags path must leave PGPASSWORD intact.
        cmd = _db_admin_psql_command(self.remote, "SELECT 1;", psql_flags="-tA")
        self.assertIn("-tA -c", cmd)
        # Password with a "-c" substring must survive intact (the old
        # .replace("-c", "-tA -c", 1) would have mangled it to "se-tA -cret").
        self.assertIn("PGPASSWORD=se-cret", cmd)
        self.assertNotIn("se-tA", cmd)

    def test_no_flags_has_no_tuples_output(self) -> None:
        cmd = _db_admin_psql_command(self.local, "SELECT 1;")
        self.assertNotIn("-tA", cmd)
        self.assertIn(" -c ", cmd)


if __name__ == "__main__":
    unittest.main()
