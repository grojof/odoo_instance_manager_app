"""Guards on the paths that remove or overwrite: install over an existing instance,
the cleanup of a failed install, purge, delete, backup directories and retention."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instance_manager import planners
from instance_manager.models import InstanceConfig, reserved_name_error
from instance_manager.workflows import common, install, purge
from instance_manager.workflows.diskusage import _backed_up_databases


def _no_host_artifacts():
    return mock.patch.multiple(
        common, path_exists=mock.DEFAULT, service_exists=mock.DEFAULT, user_exists=mock.DEFAULT,
    )


class ReservedNameTests(unittest.TestCase):
    def test_system_accounts_and_services_are_refused(self) -> None:
        for name in ("backup", "nginx", "postgres", "ssh", "root", "ubuntu", "cron"):
            self.assertIsNotNone(reserved_name_error(name), name)

    def test_an_instance_name_is_accepted(self) -> None:
        self.assertIsNone(reserved_name_error("shop"))


class NewInstanceNameTests(unittest.TestCase):
    def test_a_free_name_is_accepted(self) -> None:
        with _no_host_artifacts() as probes:
            for probe in probes.values():
                probe.return_value = False
            self.assertIsNone(install._new_instance_name_error("shop"))

    def test_an_existing_home_unit_or_user_is_refused(self) -> None:
        for present in ("path_exists", "service_exists", "user_exists"):
            with _no_host_artifacts() as probes:
                for name, probe in probes.items():
                    probe.return_value = name == present
                self.assertIsNotNone(install._new_instance_name_error("shop"), present)

    def test_a_reserved_name_is_refused_before_any_probe(self) -> None:
        with _no_host_artifacts() as probes:
            self.assertIsNotNone(install._new_instance_name_error("backup"))
            for probe in probes.values():
                probe.assert_not_called()

    def test_a_db_only_install_checks_the_format_only(self) -> None:
        self.assertIsNone(install._new_instance_name_error("backup", with_odoo=False))
        self.assertIsNotNone(install._new_instance_name_error("Bad-Name", with_odoo=False))


class InstallCleanupTests(unittest.TestCase):
    def _config(self) -> InstanceConfig:
        config = InstanceConfig(instance="shop", data_dir="/var/lib/odoo/shop")
        config.normalize_defaults()
        return config

    def test_a_data_dir_that_was_there_is_kept(self) -> None:
        cmds = install._build_partial_install_cleanup(self._config(), cleanup_db_role=False)
        self.assertFalse(any("/var/lib/odoo/shop" in c.command for c in cmds))

    def test_a_data_dir_this_run_made_is_removed(self) -> None:
        cmds = install._build_partial_install_cleanup(
            self._config(), cleanup_db_role=False, data_dir_is_new=True
        )
        self.assertIn("rm -rf /var/lib/odoo/shop", [c.command for c in cmds])

    def test_the_user_log_and_logrotate_policy_are_removed(self) -> None:
        joined = "\n".join(c.command for c in install._build_partial_install_cleanup(self._config(), False))
        self.assertIn("userdel shop", joined)
        self.assertNotIn("userdel -r", joined)
        self.assertIn("/etc/logrotate.d/odoo-shop", joined)

    def test_a_db_only_cleanup_drops_only_the_new_role(self) -> None:
        cmds = install._build_partial_install_cleanup(self._config(), True, with_odoo=False)
        self.assertEqual(len(cmds), 1)
        self.assertIn('DROP ROLE IF EXISTS "shop";', cmds[0].command)

    def test_cancel_or_ctrl_c_at_the_confirmation_runs_nothing(self) -> None:
        config = self._config()
        with mock.patch.object(install, "apply_commands") as apply, \
                mock.patch.object(install, "_confirm_plan", return_value=False):
            install._execute_install_with_cleanup([mock.Mock()], config, cleanup_db_role=True)
        apply.assert_not_called()
        with mock.patch.object(install, "apply_commands") as apply, \
                mock.patch.object(install, "_confirm_plan", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                install._execute_install_with_cleanup([mock.Mock()], config, cleanup_db_role=True)
        apply.assert_not_called()

    def test_a_failure_while_running_offers_the_previewed_cleanup(self) -> None:
        config = self._config()
        with mock.patch.object(install, "_confirm_plan", return_value=True), \
                mock.patch.object(install, "require_root_for_apply"), \
                mock.patch.object(install, "path_exists", return_value=True), \
                mock.patch.object(install, "preview_commands") as preview, \
                mock.patch.object(install, "ask_bool", return_value=True), \
                mock.patch.object(install, "apply_commands", side_effect=[RuntimeError("x"), None]) as apply:
            install._execute_install_with_cleanup([mock.Mock()], config, cleanup_db_role=False)
        preview.assert_called_once()
        cleanup = apply.call_args_list[1].args[0]
        # The data dir existed before the run: the cleanup leaves it.
        self.assertFalse(any("/var/lib/odoo/shop" in c.command for c in cleanup))


class DataDirTests(unittest.TestCase):
    def test_the_config_being_built_wins_over_the_disk(self) -> None:
        config = InstanceConfig(instance="dev", data_dir="/var/lib/odoo/dev")
        with mock.patch.object(common, "read_odoo_conf") as read:
            self.assertEqual(common._resolve_data_dir(config), "/var/lib/odoo/dev")
        read.assert_not_called()

    def test_the_legacy_conf_location_is_read(self) -> None:
        config = InstanceConfig(instance="old")
        confs = {"/etc/old/odoo.conf": {"data_dir": "/srv/old-data"}}
        with mock.patch.object(common, "read_odoo_conf", side_effect=lambda p: confs.get(p, {})):
            self.assertEqual(common._resolve_data_dir(config), "/srv/old-data")

    def test_private_and_shared_data_dirs(self) -> None:
        config = InstanceConfig(instance="shop")
        self.assertTrue(common._data_dir_is_private(config, "/var/lib/odoo/shop"))
        self.assertTrue(common._data_dir_is_private(config, "/opt/odoo/shop/.local/share/Odoo"))
        self.assertFalse(common._data_dir_is_private(config, "/var/lib/odoo"))
        self.assertFalse(common._data_dir_is_private(config, "/opt/odoo/shop2/data"))


class BackupDirTests(unittest.TestCase):
    def test_shared_or_relative_directories_are_refused(self) -> None:
        for path in ("/", "/tmp", "/tmp/", "/var/backups", "/etc", "/opt/odoo", "backups", "/a/../tmp"):
            self.assertIsNotNone(common._backup_dir_error(path), path)

    def test_a_dedicated_directory_is_accepted(self) -> None:
        self.assertIsNone(common._backup_dir_error("/var/backups/shop"))
        self.assertIsNone(common._backup_dir_error("/srv/backups/odoo/shop"))


class RetentionTests(unittest.TestCase):
    def test_newest_by_name_not_by_mtime(self) -> None:
        command = planners._prune_command("/b", "'x--*'", 3)
        self.assertNotIn("%T@", command)
        self.assertIn("sort -r |", command)
        self.assertIn("tail -n +4", command)

    def test_database_names_from_file_names_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("shop--prod--20261001_020000.dump", "shop--$(x)--20261001_020000.dump",
                         "shop---x--20261001_020000.dump"):
                (Path(tmp) / name).touch()
            self.assertEqual(_backed_up_databases(InstanceConfig(instance="shop"), tmp), ["prod"])


class PurgeTests(unittest.TestCase):
    session = purge.DbAdminSession("local", "127.0.0.1", 5432, "", "")

    def test_administrator_roles_are_refused(self) -> None:
        self.assertIsNotNone(purge._superuser_role_error(self.session, "postgres"))
        with mock.patch.object(purge, "_query_names", return_value=(["t"], None)):
            self.assertIsNotNone(purge._superuser_role_error(self.session, "admin_role"))
        with mock.patch.object(purge, "_query_names", return_value=(["f"], None)):
            self.assertIsNone(purge._superuser_role_error(self.session, "shop"))
        with mock.patch.object(purge, "_query_names", return_value=([], "no server")):
            self.assertIsNotNone(purge._superuser_role_error(self.session, "shop"))

    def _remove(self, data_dir: str, managed_exists: bool = False) -> list[str]:
        config = InstanceConfig(instance="shop")
        with mock.patch.object(purge, "_resolve_data_dir", return_value=data_dir), \
                mock.patch.object(purge.os.path, "isdir", return_value=managed_exists):
            return [c.command for c in purge._remove_data_commands(config, ["shop", "shop_test"])]

    def test_a_shared_data_dir_loses_only_the_selected_filestores(self) -> None:
        cmds = self._remove("/var/lib/odoo")
        self.assertEqual(cmds, [
            "rm -rf /var/lib/odoo/filestore/shop", "rm -rf /var/lib/odoo/filestore/shop_test",
        ])

    def test_the_managed_data_dir_is_removed_whole(self) -> None:
        self.assertEqual(self._remove("/var/lib/odoo/shop"), ["rm -rf /var/lib/odoo/shop"])

    def test_a_data_dir_in_the_home_goes_with_the_home(self) -> None:
        self.assertEqual(self._remove("/opt/odoo/shop/.local/share/Odoo"), [])

    def test_after_a_delete_the_managed_data_dir_is_still_found(self) -> None:
        cmds = self._remove("/opt/odoo/shop/.local/share/Odoo", managed_exists=True)
        self.assertEqual(cmds, ["rm -rf /var/lib/odoo/shop"])


class LogDirTests(unittest.TestCase):
    def test_no_instance_takes_the_shared_log_directory(self) -> None:
        config = InstanceConfig(instance="shop")
        config.normalize_defaults()
        joined = "\n".join(c.command for c in planners.plan_odoo_base_setup(config))
        self.assertNotRegex(joined, r"chown -R [^\n]*/var/log/odoo( |$)")
        self.assertIn("chown root:root /var/log/odoo", joined)
        self.assertIn("chown shop:shop /var/log/odoo/shop.log && chmod 640 /var/log/odoo/shop.log", joined)


if __name__ == "__main__":
    unittest.main()
