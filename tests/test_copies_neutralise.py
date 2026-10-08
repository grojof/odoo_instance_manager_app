"""Copies: the catalogue's new rules, Odoo's own neutralize.sql, and the staged
copy that is done whole or dropped."""

from __future__ import annotations

import unittest
from unittest import mock

from instance_manager import neutralise
from instance_manager.models import InstanceConfig
from instance_manager.system import Command
from instance_manager.workflows import backup_restore

URL = "http://127.0.0.1:8069"


def _rule(rule_id: str) -> neutralise.Rule:
    return next(r for r in neutralise.CATALOGUE if r.id == rule_id)


class CatalogueTests(unittest.TestCase):
    def test_spanish_test_modes_per_version(self) -> None:
        # Fields as each version's res_company declares them (odoo 14.0-19.0, OCA l10n-spain).
        self.assertEqual(_rule("spain-edi-odoo").sets, (("l10n_es_edi_test_env", "true"),))
        self.assertEqual(_rule("sii-odoo").sets, (("l10n_es_sii_test_env", "true"),))
        self.assertEqual(_rule("verifactu-odoo").sets, (("l10n_es_edi_verifactu_test_environment", "true"),))
        self.assertEqual(_rule("verifactu-oca").sets, (("verifactu_test", "true"),))
        self.assertEqual(_rule("ticketbai-oca").sets, (("tbai_test_enabled", "true"),))

    def test_secrets_without_a_harmless_value_are_deleted(self) -> None:
        sql = neutralise.apply_sql(URL)
        self.assertIn("DELETE FROM ir_config_parameter t WHERE (t.key IN ('mail.web_push_vapid_private_key'", sql)
        self.assertIn("DELETE FROM mail_push_device t WHERE (true)", sql)
        self.assertIn("'cloud_storage_azure_client_secret'", sql)

    def test_mail_servers_point_nowhere_and_the_sink_logs_in(self) -> None:
        self.assertIn(("smtp_host", "'invalid'"), _rule("mail-servers").sets)
        sql = neutralise.apply_sql(URL)
        self.assertIn("'smtp_authentication', 'login'", sql)
        self.assertIn("UPDATE ir_mail_server SET smtp_authentication = 'login'", sql)
        self.assertIn("smtp_authentication = 'cli'", neutralise.guard_sql(URL))

    def test_the_edi_proxy_parameter_of_14_to_16(self) -> None:
        sql = neutralise.apply_sql(URL)
        self.assertIn("INSERT INTO ir_config_parameter (key, value) VALUES ('account_edi_proxy_client.demo', 'true')",
                      sql)
        self.assertIn("edi-proxy-demo (missing)", neutralise.guard_sql(URL))
        old = {("account_edi_proxy_client_user", "id")}
        self.assertTrue(neutralise.edi_param_armed(old))
        self.assertFalse(neutralise.edi_param_armed(old | {("account_edi_proxy_client_user", "edi_mode")}))
        self.assertIn("'edi-proxy-demo'", neutralise.check_sql([], URL, edi_param=True))

    def test_long_iap_tokens_are_replaced_whole(self) -> None:
        [(column, expr)] = _rule("iap").sets
        self.assertEqual(column, "account_token")
        self.assertIn("length(t.account_token) <= 33", expr)
        self.assertIn("'dummy_value+disabled'", expr)

    def test_a_rule_without_its_label_still_applies(self) -> None:
        existing = {("iap_account", "id"), ("iap_account", "account_token")}
        [rule] = [r for r in neutralise.applicable(existing) if r.id == "iap"]
        self.assertEqual(rule.label, "")
        self.assertIn("t.id::text", neutralise.check_sql([rule], URL))


class OdooNeutralizeTests(unittest.TestCase):
    def test_reads_the_checkout_as_its_user_and_runs_as_the_owner(self) -> None:
        reader = InstanceConfig(instance="prod")
        with mock.patch.object(backup_restore, "_addons_paths", return_value=["/opt/odoo/prod/odoo/addons"]):
            command = backup_restore._odoo_neutralize_command(
                backup_restore._psql_target_local("copy"), "dev", reader, None).command
        self.assertIn("ir_module_module WHERE state IN (", command)
        self.assertIn("to upgrade", command)
        self.assertIn("sudo -u prod -H bash -c", command)
        self.assertIn("/opt/odoo/prod/odoo/addons", command)
        self.assertIn('SET ROLE "dev"; SET search_path = public;', command)
        self.assertTrue(command.rstrip().endswith("-v ON_ERROR_STOP=1 -1"))

    def test_it_runs_before_the_catalogue(self) -> None:
        with mock.patch.object(backup_restore, "_addons_paths", return_value=[]):
            steps = backup_restore._post_db_mode_commands(
                "psql", "Moved (keep UUID)", True, URL, role="dev", odoo_sql_reader=InstanceConfig(instance="p"))
        self.assertIn("neutralize.sql", steps[0].description)
        self.assertIn("Neutralise the copy", steps[1].description)


class StagedCopyTests(unittest.TestCase):
    def test_only_a_database_it_created_is_dropped(self) -> None:
        command = backup_restore._staged_copy_command(
            "copy", "dev", Command("Create", "createdb dev"), [Command("Fill", "false")], "dropdb dev",
            "systemctl start shop").command
        lines = command.splitlines()
        self.assertEqual(lines[0], "set -e")
        self.assertLess(lines.index("createdb dev"), lines.index("created=1"))
        self.assertIn('if [ -n "$created" ]', command)
        self.assertIn("systemctl start shop", command)

    def test_the_copy_is_closed_until_the_hand_over(self) -> None:
        seed = backup_restore._seed_db_commands("prod", "dev", "dev", "dump")
        joined = "\n".join(c.command for c in seed)
        self.assertIn(backup_restore.STAGING_COMMENT, joined)
        self.assertNotIn("GRANT CONNECT", joined)

    def test_the_whole_copy_is_one_step(self) -> None:
        with mock.patch.object(backup_restore, "_addons_paths", return_value=[]):
            command = backup_restore._local_copy_command(
                "copy", "dev", "dev", backup_restore._seed_db_commands("prod", "dev", "dev", "dump"),
                "Copied (new UUID on target)", True, URL, InstanceConfig(instance="prod")).command
        for part in ("createdb dev", "pg_restore", "database.uuid", "neutralize.sql", "can still act",
                     'OWNER TO "dev"', "dropdb --if-exists --force dev"):
            self.assertIn(part, command, part)


if __name__ == "__main__":
    unittest.main()
