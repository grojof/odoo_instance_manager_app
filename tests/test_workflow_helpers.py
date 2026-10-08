"""Tests for pure workflow helpers touched by the data-operation fixes."""

from __future__ import annotations

import unittest

from instance_manager.models import InstanceConfig
from instance_manager.workflows.common import _keep_data_dir_commands
from instance_manager.workflows.purge import (
    DbAdminSession,
    _db_admin_psql_command,
    _instance_databases_sql,
    _prefix_only_databases_sql,
)


class KeepDataDirTests(unittest.TestCase):
    def test_data_dir_inside_home_is_moved_out_before_removal(self) -> None:
        config = InstanceConfig(instance="shop")
        cmds = _keep_data_dir_commands(config, "/opt/odoo/shop/.local/share/Odoo", "20261008_010203")
        self.assertEqual(len(cmds), 1)
        self.assertIn(
            "mv -- /opt/odoo/shop/.local/share/Odoo /var/backups/shop/kept-data-dir-20261008_010203",
            cmds[0].command,
        )
        self.assertIn("install -d -m 700 /var/backups/shop", cmds[0].command)

    def test_data_dir_outside_home_needs_nothing(self) -> None:
        config = InstanceConfig(instance="shop")
        self.assertEqual(_keep_data_dir_commands(config, "/var/lib/odoo/shop"), [])
        # A sibling sharing the prefix is not "inside".
        self.assertEqual(_keep_data_dir_commands(config, "/opt/odoo/shop2/data"), [])


class PurgeDiscoveryTests(unittest.TestCase):
    def test_selects_by_owner_or_exact_name_only(self) -> None:
        sql = _instance_databases_sql("shop", "shop_role")
        self.assertIn("d.datname = 'shop'", sql)
        self.assertIn("r.rolname = 'shop_role'", sql)
        self.assertNotIn("LIKE", sql)

    def test_a_shared_role_does_not_select_by_owner(self) -> None:
        sql = _instance_databases_sql("shop", "odoo", by_owner=False)
        self.assertIn("d.datname = 'shop'", sql)
        self.assertNotIn("rolname", sql)

    def test_prefix_matches_are_escaped_and_only_reported(self) -> None:
        sql = _prefix_only_databases_sql("shop_eu", "shop_eu")
        # `_` is a LIKE wildcard: it is escaped so `shopXeu` is not matched.
        self.assertIn("LIKE 'shop\\_eu%'", sql)
        self.assertIn("r.rolname <> 'shop_eu'", sql)


class DbAdminPsqlCommandTests(unittest.TestCase):
    local = DbAdminSession("local", "127.0.0.1", 5432, "", "")
    remote = DbAdminSession("remote", "db.example", 5432, "postgres", "se-cret")

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
