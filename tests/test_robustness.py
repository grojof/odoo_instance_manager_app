"""Robustness: the entry point's arguments, the file picker, the health probe and
scheduled backups of a remote database."""

from __future__ import annotations

import http.client
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import odoo_instance_manager
from instance_manager import prompts
from instance_manager.models import InstanceConfig
from instance_manager.workflows import health, scheduled_backup


class EntryPointTests(unittest.TestCase):
    def test_help_and_version_need_no_root(self) -> None:
        with mock.patch.object(odoo_instance_manager.os, "geteuid", return_value=1000):
            for args in (["--help"], ["-h"], ["--version"]):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(odoo_instance_manager.main(args), 0, args)
                self.assertIn("odoo-instance-manager", out.getvalue())

    def test_unknown_arguments_are_refused(self) -> None:
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(odoo_instance_manager.main(["--purge-everything"]), 2)


class PickerTests(unittest.TestCase):
    def test_an_out_of_range_number_is_not_a_path(self) -> None:
        answers = iter(["99", "q"])
        with mock.patch("builtins.input", lambda *_: next(answers)), redirect_stdout(io.StringIO()):
            self.assertEqual(prompts.select_file_path("/"), "")


class HealthProbeTests(unittest.TestCase):
    def test_a_port_that_does_not_speak_http_is_not_a_crash(self) -> None:
        with mock.patch.object(health.urllib.request, "urlopen", side_effect=http.client.BadStatusLine("x")):
            ok, detail = health._http_probe("8069")
        self.assertFalse(ok)


class ScheduledBackupTests(unittest.TestCase):
    def test_a_remote_database_is_refused(self) -> None:
        with mock.patch.object(scheduled_backup, "read_odoo_conf", return_value={"db_host": "db.example.com"}), \
                mock.patch.object(scheduled_backup, "ask_text") as ask, \
                mock.patch.object(scheduled_backup, "_execute_plan") as execute, redirect_stdout(io.StringIO()):
            scheduled_backup._configure_schedule(InstanceConfig(instance="shop"))
        ask.assert_not_called()
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
