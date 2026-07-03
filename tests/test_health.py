"""Tests for the instance health-check probes."""

from __future__ import annotations

import subprocess
import unittest
import urllib.error

from instance_manager.ui import strip_ansi
from instance_manager.workflows import health


class HttpProbeTests(unittest.TestCase):
    def test_non_numeric_port_is_unhealthy(self) -> None:
        ok, detail = health._http_probe("false")
        self.assertFalse(ok)
        self.assertIn("no numérico", detail)

    def test_2xx_response_is_healthy(self) -> None:
        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        self.addCleanup(setattr, health.urllib.request, "urlopen", health.urllib.request.urlopen)
        health.urllib.request.urlopen = lambda *a, **k: _Resp()
        ok, detail = health._http_probe("8069")
        self.assertTrue(ok)
        self.assertIn("200", detail)

    def test_no_response_is_unhealthy(self) -> None:
        def _boom(*a, **k):
            raise urllib.error.URLError("refused")

        self.addCleanup(setattr, health.urllib.request, "urlopen", health.urllib.request.urlopen)
        health.urllib.request.urlopen = _boom
        ok, detail = health._http_probe("8069")
        self.assertFalse(ok)
        self.assertIn("sin respuesta", detail)


class DiskRowTests(unittest.TestCase):
    def _patch(self, exists: bool, df_stdout: str) -> None:
        self.addCleanup(setattr, health, "path_exists", health.path_exists)
        self.addCleanup(setattr, health, "run", health.run)
        health.path_exists = lambda _p: exists
        health.run = lambda *a, **k: subprocess.CompletedProcess("df", 0, df_stdout, "")

    def test_high_usage_flags_missing(self) -> None:
        self._patch(True, "/dev/sda1 100G 95G 5G 95% /")
        tag, label, detail = health._disk_row("Disco", "/opt/odoo/x")
        self.assertIn("MISSING", strip_ansi(tag))
        self.assertIn("95%", detail)

    def test_normal_usage_is_ok(self) -> None:
        self._patch(True, "/dev/sda1 100G 40G 60G 40% /")
        tag, _label, _detail = health._disk_row("Disco", "/opt/odoo/x")
        self.assertIn("OK", strip_ansi(tag))

    def test_missing_path_is_info(self) -> None:
        self._patch(False, "")
        tag, _label, detail = health._disk_row("Disco", "/nope")
        self.assertIn("INFO", strip_ansi(tag))
        self.assertIn("no existe", detail)


if __name__ == "__main__":
    unittest.main()
