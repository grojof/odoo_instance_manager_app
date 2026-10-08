"""Tests for the duplicate-instance database command and name safety."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instance_manager.models import InstanceConfig
from instance_manager.workflows import backup_restore
from instance_manager.workflows.backup_restore import (
    _drop_db_commands,
    _filestore_copy_commands,
    _is_safe_db_name,
    _nginx_server_name_in_use,
    _post_db_mode_commands,
    _psql_target_local,
    _replicate_venv_packages_command,
    _seed_db_commands,
    _template_copy_script,
)


class ReplicateVenvPackagesTests(unittest.TestCase):
    def test_freezes_source_and_installs_into_target(self) -> None:
        cmd = _replicate_venv_packages_command(
            InstanceConfig(instance="prod"), InstanceConfig(instance="dev")
        ).command
        self.assertIn("sudo -u prod /opt/odoo/prod/venv/bin/pip freeze", cmd)
        self.assertIn("grep -E '^[A-Za-z0-9_.-]+=='", cmd)
        self.assertIn("sudo -u dev /opt/odoo/dev/venv/bin/pip install -r", cmd)


class SafeDbNameTests(unittest.TestCase):
    def test_accepts_typical_names(self) -> None:
        for name in ("odoo18test", "ab", "shop_prod", "a-b.c_d", "db01", "Shop2"):
            self.assertTrue(_is_safe_db_name(name), name)

    def test_rejects_unsafe_names(self) -> None:
        # Odoo's DBNAME_PATTERN: no leading symbol (a leading '-' would be read as an
        # option by createdb/dropdb), at least two characters, nothing a shell or SQL
        # string could misread.
        for name in ("", "a", "bad name", "a;drop", 'a"b', "a'b", "a`b", "a$(id)", "x" * 64, "-lead", "_lead", ".x"):
            self.assertFalse(_is_safe_db_name(name), name)


class TemplateCopyScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = _template_copy_script("shop", "shopdev", "shop")

    def test_closes_the_source_before_copy(self) -> None:
        lines = self.script.splitlines()
        close = next(i for i, line in enumerate(lines) if 'ALLOW_CONNECTIONS false' in line)
        terminate = next(i for i, line in enumerate(lines) if "pg_terminate_backend" in line)
        copy = next(i for i, line in enumerate(lines) if "createdb -T shop" in line)
        self.assertLess(close, terminate)
        self.assertLess(terminate, copy)
        self.assertIn("datname = 'shop'", self.script)

    def test_always_reopens_the_source(self) -> None:
        self.assertIn("trap reopen EXIT", self.script)
        self.assertIn('ALTER DATABASE "shop" WITH ALLOW_CONNECTIONS true;', self.script)

    def test_seed_uses_it(self) -> None:
        joined = "\n".join(c.command for c in _seed_db_commands("shop", "shopdev", "shop", "template"))
        self.assertIn(self.script, joined)


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

    def test_seed_locks_db_access_to_owner(self) -> None:
        for method in ("dump", "template"):
            joined = "\n".join(c.command for c in _seed_db_commands("prod", "dev", "dev", method))
            self.assertIn('REVOKE CONNECT ON DATABASE "dev" FROM PUBLIC;', joined)
            self.assertIn('GRANT CONNECT ON DATABASE "dev" TO "dev";', joined)


class DropDbCommandsTests(unittest.TestCase):
    def test_drops_with_force(self) -> None:
        # --force closes the sessions and refuses new ones in the same statement.
        joined = "\n".join(c.command for c in _drop_db_commands("dev"))
        self.assertIn("dropdb --if-exists --force dev", joined)


class DuplicateGuardTests(unittest.TestCase):
    def _owners(self, owners: dict[str, str]):
        return mock.patch.object(backup_restore, "database_owner", side_effect=owners.get)

    def test_existing_target_of_another_role_is_refused(self) -> None:
        # Typing production's name as the refresh target must not drop it.
        with self._owners({"prod": "prod"}):
            self.assertIsNotNone(backup_restore._existing_target_error("prod", "dev"))

    def test_target_of_its_own_role_or_absent_is_allowed(self) -> None:
        with self._owners({"dev": "dev"}):
            self.assertIsNone(backup_restore._existing_target_error("dev", "dev"))
            self.assertIsNone(backup_restore._existing_target_error("absent", "dev"))

    def test_template_copy_needs_the_same_owner(self) -> None:
        with self._owners({"prod": "prod"}):
            self.assertIsNotNone(backup_restore._template_owner_error("prod", "dev"))
            self.assertIsNone(backup_restore._template_owner_error("prod", "prod"))


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
        # The whole data dir is chowned (so Odoo can create sessions/), not just filestore.
        self.assertIn("chown -R dev:dev /opt/odoo/dev/.local/share/Odoo", joined)
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
