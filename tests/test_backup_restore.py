"""Tests for the duplicate-instance database command and name safety."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from instance_manager.models import InstanceConfig
from instance_manager.workflows.backup_restore import (
    _drop_db_commands,
    _duplicate_db_command,
    _filestore_copy_commands,
    _is_safe_db_name,
    _nginx_server_name_in_use,
    _post_db_mode_commands,
    _psql_target_local,
    _seed_db_commands,
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


class SeedDbCommandsTests(unittest.TestCase):
    def test_dump_method_reassigns_ownership(self) -> None:
        cmds = [c.command for c in _seed_db_commands("prod", "dev", "dev", "dump")]
        joined = "\n".join(cmds)
        self.assertIn("sudo -u postgres createdb -O dev dev", joined)
        self.assertIn("sudo -u postgres pg_dump -Fc prod", joined)
        self.assertIn("pg_restore -d dev --no-owner --role=dev --no-privileges", joined)
        self.assertIn("set -o pipefail", joined)

    def test_template_method_frees_source(self) -> None:
        cmds = [c.command for c in _seed_db_commands("prod", "dev", "dev", "template")]
        joined = "\n".join(cmds)
        self.assertIn("pg_terminate_backend", joined)
        self.assertIn("datname = 'prod'", joined)
        self.assertIn("createdb -T prod -O dev dev", joined)


class DropDbCommandsTests(unittest.TestCase):
    def test_terminates_then_drops(self) -> None:
        cmds = [c.command for c in _drop_db_commands("dev")]
        joined = "\n".join(cmds)
        self.assertIn("pg_terminate_backend", joined)
        self.assertIn("datname = 'dev'", joined)
        self.assertIn("dropdb --if-exists dev", joined)


class PostDbModeLocalTests(unittest.TestCase):
    def test_copied_and_neutralize_via_local_superuser(self) -> None:
        cmds = [c.command for c in _post_db_mode_commands(_psql_target_local("dev"), "Copied (new UUID on target)", True)]
        joined = "\n".join(cmds)
        self.assertIn("sudo -u postgres psql -d dev", joined)
        self.assertIn("database.uuid", joined)
        self.assertIn("UPDATE ir_cron SET active = false;", joined)
        self.assertIn("UPDATE ir_mail_server SET active = false;", joined)

    def test_moved_without_neutralize_is_empty(self) -> None:
        cmds = _post_db_mode_commands(_psql_target_local("dev"), "Moved (keep UUID)", False)
        self.assertEqual(cmds, [])


class FilestoreCopyTests(unittest.TestCase):
    def test_copies_into_target_and_owns_it(self) -> None:
        source = InstanceConfig(instance="prod")
        target = InstanceConfig(instance="dev")
        cmds = [c.command for c in _filestore_copy_commands(source, "prod", target, "dev", overwrite=False)]
        joined = "\n".join(cmds)
        self.assertIn("cp -a", joined)
        self.assertIn("/opt/odoo/prod/.local/share/Odoo/filestore/prod", joined)
        self.assertIn("/opt/odoo/dev/.local/share/Odoo/filestore/dev", joined)
        self.assertIn("chown -R dev:dev", joined)
        self.assertNotIn("rm -rf", joined)

    def test_overwrite_removes_previous_target(self) -> None:
        source = InstanceConfig(instance="prod")
        target = InstanceConfig(instance="dev")
        cmds = [c.command for c in _filestore_copy_commands(source, "prod", target, "dev", overwrite=True)]
        self.assertTrue(any("rm -rf" in c and "filestore/dev" in c for c in cmds))


class NginxServerNameInUseTests(unittest.TestCase):
    def _dir_with_vhost(self, tmp: str, server_names: str) -> str:
        (Path(tmp) / "shop-https.conf").write_text(
            f"server {{\n  listen 443 ssl;\n  server_name {server_names};\n}}\n",
            encoding="utf-8",
        )
        return tmp

    def test_detects_used_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._dir_with_vhost(tmp, "shop.example.com")
            self.assertTrue(_nginx_server_name_in_use("shop.example.com", tmp))

    def test_free_domain_is_not_in_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._dir_with_vhost(tmp, "shop.example.com")
            self.assertFalse(_nginx_server_name_in_use("dev.example.com", tmp))

    def test_empty_or_missing_dir_is_false(self) -> None:
        self.assertFalse(_nginx_server_name_in_use("", "/nonexistent"))
        self.assertFalse(_nginx_server_name_in_use("x.example.com", "/nonexistent/dir"))


if __name__ == "__main__":
    unittest.main()
