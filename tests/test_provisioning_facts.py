"""Provisioning facts: odoo.conf read and merged as Odoo reads it, scram passwords,
nginx directives by version."""

from __future__ import annotations

import configparser
import tempfile
import unittest
from pathlib import Path

from instance_manager import planners, system
from instance_manager.models import InstanceConfig

OLD_CONF = """[options]
admin_passwd = old
addons_path = /opt/odoo/shop/odoo/addons,
    /opt/odoo/shop/addons-oca
Data_Dir = /var/lib/odoo/shop
data_dir = /var/lib/odoo/shop
smtp_server = mail.example.com

[queue_job]
channels = root:2
"""


class OdooConfTests(unittest.TestCase):
    def _merged(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shop.conf"
            path.write_text(OLD_CONF, encoding="utf-8")
            existing = system.read_odoo_conf(str(path))
            other = system.read_conf_other_sections(str(path))
        config = InstanceConfig(instance="shop", data_dir="/var/lib/odoo/shop")
        config.normalize_defaults()
        config.ensure_strong_secrets()
        return planners.render_merged_odoo_conf(config, existing, other)

    def test_read_as_odoo_reads_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shop.conf"
            path.write_text(OLD_CONF, encoding="utf-8")
            values = system.read_odoo_conf(str(path))
        self.assertEqual(values["addons_path"], "/opt/odoo/shop/odoo/addons,\n/opt/odoo/shop/addons-oca")
        self.assertNotIn("channels", values)
        self.assertNotIn("Data_Dir", values)

    def test_the_merge_parses_whole_and_keeps_other_sections(self) -> None:
        parser = configparser.RawConfigParser()  # strict, as a duplicate would fail
        parser.read_string(self._merged())
        self.assertEqual(parser.sections(), ["options", "queue_job"])
        self.assertEqual(parser["options"]["addons_path"], "/opt/odoo/shop/odoo/addons,\n/opt/odoo/shop/addons-oca")
        self.assertEqual(parser["options"]["smtp_server"], "mail.example.com")
        self.assertEqual(parser["queue_job"]["channels"], "root:2")

    def test_a_file_without_header_and_bad_bytes_is_still_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.conf"
            path.write_bytes(b"db_user = shop\nlogfile = /var/log/\xff.log\n")
            values = system.read_odoo_conf(str(path))
        self.assertEqual(values["db_user"], "shop")


class PasswordStorageTests(unittest.TestCase):
    def test_passwords_are_set_as_scram(self) -> None:
        config = InstanceConfig(instance="shop")
        config.normalize_defaults()
        config.ensure_strong_secrets()
        self.assertTrue(planners._db_role_create_if_missing_sql(config).startswith(
            "SET password_encryption = 'scram-sha-256'; "))


if __name__ == "__main__":
    unittest.main()


class WkhtmltopdfAssetTests(unittest.TestCase):
    def test_assets_follow_the_machine(self) -> None:
        from instance_manager.planners import resolve_wkhtmltopdf_asset
        self.assertIn("jammy_amd64", resolve_wkhtmltopdf_asset("noble", "x86_64")[1])
        self.assertIn("jammy_arm64", resolve_wkhtmltopdf_asset("noble", "aarch64")[1])
        self.assertIn("bookworm_arm64", resolve_wkhtmltopdf_asset("bookworm", "aarch64")[1])
        # Debian 13 and Ubuntu 26.04 have no compatible build; nor has another machine.
        self.assertIsNone(resolve_wkhtmltopdf_asset("trixie", "x86_64"))
        self.assertIsNone(resolve_wkhtmltopdf_asset("jammy", "riscv64"))


class AptCandidateTests(unittest.TestCase):
    def test_versions_from_apt_cache_policy(self) -> None:
        from unittest import mock
        out = "nginx:\n  Installed: (none)\n  Candidate: 1.18.0-6ubuntu14.4\n"
        with mock.patch.object(system, "run", return_value=mock.Mock(stdout=out, returncode=0)), \
                mock.patch.object(system, "command_ok", return_value=False):
            self.assertEqual(system.apt_candidate("nginx"), "1.18.0-6ubuntu14.4")
            self.assertEqual(system.detect_nginx_version(), (1, 18, 0))
        none = "wkhtmltopdf:\n  Installed: (none)\n  Candidate: (none)\n"
        with mock.patch.object(system, "run", return_value=mock.Mock(stdout=none, returncode=0)):
            self.assertEqual(system.apt_candidate("wkhtmltopdf"), "")


class ExistingRoleTests(unittest.TestCase):
    def test_an_existing_role_keeps_or_gets_the_password_as_chosen(self) -> None:
        config = InstanceConfig(instance="shop")
        config.normalize_defaults()
        config.db_password = "new-pw"
        keep = planners._db_role_create_if_missing_sql(config)
        reset = planners._db_role_create_if_missing_sql(config, reset_password=True)
        self.assertIn("ALTER ROLE shop WITH LOGIN CREATEDB; ", keep)
        self.assertIn("ALTER ROLE shop WITH LOGIN CREATEDB PASSWORD 'new-pw'; ", reset)

    def test_local_psql_names_the_port(self) -> None:
        config = InstanceConfig(instance="shop", db_port=5433)
        config.normalize_defaults()
        config.ensure_strong_secrets()
        joined = "\n".join(c.command for c in planners.plan_db_setup(config, ensure_remote_access=True))
        self.assertNotIn("sudo -u postgres psql -X -v", joined)
        self.assertIn("sudo -u postgres psql -X -p 5433", joined)
        self.assertIn("ALTER SYSTEM SET listen_addresses", joined)
        self.assertIn("systemctl reload postgresql", joined)
        self.assertNotIn("sed -ri", joined)
