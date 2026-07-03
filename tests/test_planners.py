"""Tests for pure command-plan builders in planners.py."""

from __future__ import annotations

import unittest

from instance_manager.models import InstanceConfig
from instance_manager.planners import _logrotate_content, plan_logrotate_config


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


class PlanLogrotateConfigTests(unittest.TestCase):
    def _commands_text(self, **kwargs: object) -> str:
        commands = plan_logrotate_config(_config(), **kwargs)  # type: ignore[arg-type]
        return "\n".join(f"{c.description} :: {c.command}" for c in commands)

    def test_default_plan_writes_validates_and_installs(self) -> None:
        text = self._commands_text()
        self.assertIn("logrotate instalado", text)
        self.assertIn("/etc/logrotate.d/odoo-odoo18", text)
        self.assertIn("logrotate -d", text)

    def test_disable_odoo_internal_adds_sed_only_when_requested(self) -> None:
        self.assertNotIn("logrotate = False", self._commands_text(disable_odoo_internal=False))
        with_disable = self._commands_text(disable_odoo_internal=True)
        self.assertIn("logrotate = False", with_disable)
        self.assertIn("/etc/odoo/odoo18/odoo18.conf", with_disable)


if __name__ == "__main__":
    unittest.main()
