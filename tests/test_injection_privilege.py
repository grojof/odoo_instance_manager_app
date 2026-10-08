"""What reaches a root shell, a superuser session or the terminal: quoting, the user a
step runs as, private temporary files, and escape sequences from host text."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instance_manager import planners, system
from instance_manager.models import InstanceConfig
from instance_manager.prompts import _has_control
from instance_manager.ui import sanitize
from instance_manager.workflows import backup_restore, common, report
from instance_manager.workflows.manage import _split_requirements
from instance_manager.workflows.services import _unit_name_error

HOSTILE = "/tmp/x$(touch /tmp/pwned)'y.crt"


class CertificateTests(unittest.TestCase):
    def _config(self) -> InstanceConfig:
        return InstanceConfig(instance="shop", domain="erp.example.com")

    def test_operator_paths_are_quoted(self) -> None:
        [step] = planners.plan_copy_custom_certs(self._config(), HOSTILE, HOSTILE, HOSTILE)
        self.assertIn("cp -- '/tmp/x$(touch /tmp/pwned)'\"'\"'y.crt' \"$stage/crt\"", step.command)

    def test_files_are_checked_before_they_replace_the_live_ones(self) -> None:
        [step] = planners.plan_copy_custom_certs(self._config(), "/a.crt", "/a.key", None)
        lines = step.command.splitlines()
        first_move = next(i for i, line in enumerate(lines) if line.startswith("mv -f"))
        for check in ("openssl pkey -in", "openssl x509 -in \"$stage/crt\"", 'if [ "$cert_fp" != "$key_fp" ]'):
            self.assertLess(next(i for i, line in enumerate(lines) if check in line), first_move, check)
        self.assertEqual(lines[0], "set -e")

    def test_self_signed_domain_and_paths_are_quoted(self) -> None:
        config = self._config()
        command = planners.plan_ensure_self_signed_certs(config)[1].command
        self.assertIn("-subj /CN=erp.example.com", command)
        self.assertNotIn("'/CN=", command.replace("-subj /CN=", ""))


class RequirementSplitTests(unittest.TestCase):
    def test_a_comma_inside_a_version_range_does_not_split(self) -> None:
        self.assertEqual(_split_requirements(["babel>=2.14,<3"]), (["babel>=2.14,<3"], []))

    def test_comma_separated_names_split(self) -> None:
        self.assertEqual(_split_requirements(["requests, lxml==5.2"]), (["requests", "lxml==5.2"], []))

    def test_options_are_not_packages(self) -> None:
        packages, refused = _split_requirements(["--index-url https://evil.example", "-e ."])
        self.assertEqual(packages, [])
        self.assertEqual(refused, ["--index-url https://evil.example", "-e ."])


class InstanceUserTests(unittest.TestCase):
    def test_replica_freeze_and_install_run_as_their_owners(self) -> None:
        command = backup_restore._replicate_venv_packages_command(
            InstanceConfig(instance="prod"), InstanceConfig(instance="dev")
        ).command
        self.assertIn("sudo -u prod -H", command)
        self.assertIn("sudo -u dev -H", command)

    def test_source_git_runs_as_the_source_user(self) -> None:
        with mock.patch.object(backup_restore, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="18.0\n")
            backup_restore._detect_source_repo_branch(InstanceConfig(instance="prod"))
        self.assertTrue(run.call_args.args[0].startswith("sudo -u prod -H bash -c 'git -C /opt/odoo/prod/odoo"))

    def test_ocb_origin_forms(self) -> None:
        for origin, core in (("https://github.com/OCA/OCB.git", "ocb"), ("git@github.com:OCA/OCB.git", "ocb"),
                             ("https://github.com/OCA/OCB", "ocb"), ("https://github.com/odoo/odoo.git", "odoo"),
                             ("https://github.com/oca/ocb-fork.git", "odoo")):
            with mock.patch.object(backup_restore, "run", return_value=mock.Mock(returncode=0, stdout=origin)):
                self.assertEqual(backup_restore._detect_source_core(InstanceConfig(instance="p")), core, origin)

    def test_the_report_reads_the_venv_python_instead_of_running_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bin").mkdir()
            (Path(tmp) / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.3\n", encoding="utf-8")
            with mock.patch.object(report, "_command_output") as run:
                self.assertEqual(report._venv_python_version(f"{tmp}/bin/python3"), "Python 3.12.3")
            run.assert_not_called()
            (Path(tmp) / "pyvenv.cfg").write_text("version_info = 3.8.20.final.0\n", encoding="utf-8")
            self.assertEqual(report._venv_python_version(f"{tmp}/bin/python3"), "Python 3.8.20")

    def test_neutralisation_runs_as_the_copy_owner(self) -> None:
        commands = backup_restore._post_db_mode_commands(
            "sudo -u postgres psql -d copy", 'Copied (new UUID on target)', True, "http://127.0.0.1:8069",
            role="dev",
        )
        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertIn("SET ROLE \"dev\"; SET search_path = public; ", command.command)


class TemporaryFileTests(unittest.TestCase):
    def test_wkhtmltopdf_uses_a_private_directory_in_one_step(self) -> None:
        with mock.patch.object(planners, "resolve_wkhtmltopdf_asset",
                               return_value=("https://x/w.deb", "w.deb", "ab" * 32)):
            commands = planners.plan_install_wkhtmltopdf("patched", "noble")
        joined = "\n".join(c.command for c in commands)
        self.assertNotIn("/tmp/", joined)
        step = commands[-1].command
        self.assertIn("tmp=$(mktemp -d)", step)
        self.assertLess(step.index("sha256sum -c"), step.index("install \"$tmp\"/w.deb"))

    def test_an_export_never_follows_a_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "victim"
            target.write_text("keep", encoding="utf-8")
            link = Path(tmp) / "report.txt"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                common._write_export(str(link), "x")
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            common._write_export(str(Path(tmp) / "new.txt"), "x")
            self.assertEqual(os.stat(Path(tmp) / "new.txt").st_mode & 0o777, 0o600)


class TerminalTests(unittest.TestCase):
    def test_escape_sequences_from_the_host_are_neutralised(self) -> None:
        osc = "db\x1b]0;owned\x07name"
        self.assertEqual(sanitize(osc), "db?]0;owned?name")
        self.assertEqual(sanitize("a\x1b[2Jb"), "a?[2Jb")
        self.assertEqual(sanitize("\x9b31m"), "?31m")

    def test_colours_newlines_and_tabs_stay(self) -> None:
        self.assertEqual(sanitize("\x1b[1;31mred\x1b[0m\n\tx"), "\x1b[1;31mred\x1b[0m\n\tx")
        self.assertEqual(sanitize("50%\r", keep_cr=True), "50%\r")
        self.assertEqual(sanitize("50%\r"), "50%?")

    def test_typed_control_characters_are_refused(self) -> None:
        self.assertTrue(_has_control("^shop$\r"))
        self.assertTrue(_has_control("a\x1b[2J"))
        self.assertFalse(_has_control("p4ss w0rd!"))

    def test_unit_names(self) -> None:
        self.assertIsNone(_unit_name_error("odoo-backup-shop.timer"))
        self.assertIsNotNone(_unit_name_error("--now"))
        self.assertIsNotNone(_unit_name_error("a b"))


class SecretFormTests(unittest.TestCase):
    def test_an_escaped_secret_is_masked_too(self) -> None:
        secret = "it's"
        self.assertEqual(system.mask("PASSWORD 'it''s'", (secret,)), "PASSWORD '********'")

    def test_a_password_with_dollar_quotes_keeps_the_block_whole(self) -> None:
        config = InstanceConfig(instance="shop")
        config.normalize_defaults()
        config.db_password = "a$$b$oim0$c"
        sql = planners._db_role_create_if_missing_sql(config)
        self.assertTrue(sql.startswith("DO $oim1$ "))
        self.assertTrue(sql.endswith("$oim1$;"))


if __name__ == "__main__":
    unittest.main()
