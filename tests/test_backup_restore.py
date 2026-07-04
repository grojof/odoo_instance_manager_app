"""Tests for the duplicate-instance database command and name safety."""

from __future__ import annotations

import unittest

from instance_manager.workflows.backup_restore import (
    _duplicate_db_command,
    _is_safe_db_name,
)


class SafeDbNameTests(unittest.TestCase):
    def test_accepts_typical_names(self) -> None:
        for name in ("odoo18test", "a", "shop_prod", "a-b.c_d", "db01"):
            self.assertTrue(_is_safe_db_name(name), name)

    def test_rejects_unsafe_names(self) -> None:
        for name in ("", "bad name", "a;drop", 'a"b', "a'b", "a`b", "x" * 64, "-lead"):
            self.assertFalse(_is_safe_db_name(name), name)


class DuplicateDbCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cmd = _duplicate_db_command(
            "127.0.0.1", 5432, "shop", "s3cr3t", "shop", "shopdev"
        )

    def test_frees_the_source_before_copy(self) -> None:
        # Blocks new connections, terminates sessions, then copies.
        self.assertIn('ALTER DATABASE "shop" WITH ALLOW_CONNECTIONS false;', self.cmd)
        self.assertIn("pg_terminate_backend(pid)", self.cmd)
        self.assertIn("datname = 'shop'", self.cmd)
        self.assertIn("pid <> pg_backend_pid()", self.cmd)

    def test_template_copy(self) -> None:
        self.assertIn("createdb", self.cmd)
        self.assertIn("-T shop", self.cmd)  # shlex.quote leaves safe tokens bare
        self.assertIn("shopdev", self.cmd)

    def test_always_re_enables_source(self) -> None:
        # A trap on EXIT re-opens the source even if createdb fails.
        self.assertIn("trap reenable EXIT", self.cmd)
        self.assertIn('ALTER DATABASE "shop" WITH ALLOW_CONNECTIONS true;', self.cmd)

    def test_password_is_shell_quoted(self) -> None:
        # A value that needs quoting is shell-quoted, not interpolated raw.
        cmd = _duplicate_db_command("127.0.0.1", 5432, "shop", "p@ss w0rd", "shop", "shopdev")
        self.assertIn("export PGPASSWORD='p@ss w0rd'", cmd)


if __name__ == "__main__":
    unittest.main()
