"""Tests for pure command-plan builders in planners.py."""

from __future__ import annotations

import unittest

from instance_manager.models import InstanceConfig
from instance_manager.planners import (
    _logrotate_content,
    _nginx_logrotate_content,
    _odoo_conf_content,
    plan_backup_retention,
    plan_logrotate_config,
)


class BackupRetentionTests(unittest.TestCase):
    def test_keeps_n_newest_of_each_kind(self) -> None:
        commands = plan_backup_retention(_config(), "/var/backups/odoo18", keep=5)
        text = "\n".join(c.command for c in commands)
        # Two stanzas (dumps + filestore archives), each keeping the 5 newest.
        self.assertIn("odoo18_*.dump", text)
        self.assertIn("odoo18_*.filestore.tar.gz", text)
        self.assertIn("tail -n +6", text)  # keep 5 -> remove from the 6th onward
        self.assertIn("/var/backups/odoo18/", text)


class OdooConfContentTests(unittest.TestCase):
    def test_no_obsolete_logrotate_key(self) -> None:
        content = _odoo_conf_content(_config())
        # `logrotate` was removed from Odoo in v13; it must not be emitted.
        self.assertNotIn("logrotate", content)

    def test_current_options_present(self) -> None:
        content = _odoo_conf_content(_config())
        for key in ("proxy_mode = True", "gevent_port =", "http_port =", "logfile ="):
            self.assertIn(key, content)


def _config() -> InstanceConfig:
    config = InstanceConfig(instance="odoo18")
    config.normalize_defaults()
    return config


class LogrotateContentTests(unittest.TestCase):
    def test_includes_core_directives(self) -> None:
        content = _logrotate_content(_config(), "weekly", 14, compress=True, maxsize="")
        self.assertIn("/var/log/odoo/odoo18.log {", content)
        self.assertIn("    weekly", content)
        self.assertIn("    rotate 14", content)
        self.assertIn("    copytruncate", content)
        self.assertIn("    su odoo18 odoo18", content)
        self.assertIn("    compress", content)
        self.assertIn("    delaycompress", content)
        self.assertTrue(content.rstrip().endswith("}"))

    def test_compress_disabled_omits_compress(self) -> None:
        content = _logrotate_content(_config(), "daily", 7, compress=False, maxsize="")
        self.assertNotIn("compress", content)
        self.assertIn("    daily", content)

    def test_maxsize_included_when_set(self) -> None:
        content = _logrotate_content(_config(), "weekly", 14, compress=True, maxsize="50M")
        self.assertIn("    maxsize 50M", content)


class NginxLogrotateContentTests(unittest.TestCase):
    def test_uses_create_and_postrotate_reopen_not_copytruncate(self) -> None:
        content = _nginx_logrotate_content(_config(), "daily", 30, compress=True)
        self.assertIn("/var/log/nginx/odoo18.access.log", content)
        self.assertIn("/var/log/nginx/odoo18.error.log", content)
        self.assertIn("create 0640 www-data adm", content)
        self.assertIn("sharedscripts", content)
        self.assertIn("postrotate", content)
        self.assertIn("kill -USR1", content)
        # Nginx reopens on signal, so copytruncate must NOT be used here.
        self.assertNotIn("copytruncate", content)


class PlanLogrotateConfigTests(unittest.TestCase):
    def _commands_text(self, **kwargs: object) -> str:
        commands = plan_logrotate_config(_config(), **kwargs)  # type: ignore[arg-type]
        return "\n".join(f"{c.description} :: {c.command}" for c in commands)

    def test_default_plan_writes_validates_and_installs(self) -> None:
        text = self._commands_text()
        self.assertIn("logrotate instalado", text)
        self.assertIn("/etc/logrotate.d/odoo-odoo18", text)
        self.assertIn("logrotate -d", text)

    def test_remove_obsolete_odoo_key_adds_sed_only_when_requested(self) -> None:
        self.assertNotIn("sed", self._commands_text(remove_obsolete_odoo_key=False))
        with_cleanup = self._commands_text(remove_obsolete_odoo_key=True)
        # Deletes the obsolete logrotate line from the conf (Odoo >=13 ignores it).
        self.assertIn("/^[[:space:]]*logrotate[[:space:]]*=/d", with_cleanup)
        self.assertIn("/etc/odoo/odoo18/odoo18.conf", with_cleanup)

    def test_include_nginx_adds_nginx_stanza_only_when_requested(self) -> None:
        self.assertNotIn("/var/log/nginx/odoo18.access.log", self._commands_text(include_nginx=False))
        with_nginx = self._commands_text(include_nginx=True)
        self.assertIn("/var/log/nginx/odoo18.access.log", with_nginx)
        self.assertIn("kill -USR1", with_nginx)
        # The Odoo stanza still uses copytruncate even when Nginx is included.
        self.assertIn("copytruncate", with_nginx)


if __name__ == "__main__":
    unittest.main()
