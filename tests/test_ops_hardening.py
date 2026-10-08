"""Operations: the update's order, certificate modes, the SSH guard of UFW, and the
staged writes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instance_manager import planners
from instance_manager.models import InstanceConfig
from instance_manager.workflows import install
from instance_manager.workflows.firewall import _allows_ssh


def _config(**values) -> InstanceConfig:
    config = InstanceConfig(instance="shop", **values)
    config.normalize_defaults()
    config.ensure_strong_secrets()
    return config


class UpdateOrderTests(unittest.TestCase):
    def test_password_then_login_check_then_writes(self) -> None:
        steps = [c.description for c in planners.plan_update_instance_config(
            _config(), {}, new_db_password=True, restart=True)]
        alter = steps.index('Set the new password on the local PostgreSQL role')
        check = steps.index('Validate DB user login')
        first_write = next(i for i, d in enumerate(steps) if "/etc/odoo/shop/shop.conf" in d)
        self.assertLess(alter, check)
        self.assertLess(check, first_write)
        self.assertEqual(steps[-1], 'Restart the Odoo service to load the configuration')

    def test_a_remote_new_password_waits_for_its_server(self) -> None:
        steps = [c.description for c in planners.plan_update_instance_config(
            _config(db_host="db.example.com"), {}, new_db_password=True, restart=True)]
        self.assertNotIn('Validate DB user login', steps)
        self.assertNotIn('Restart the Odoo service to load the configuration', steps)


class CertificateModeTests(unittest.TestCase):
    def test_lets_encrypt_names_its_live_files_when_they_exist(self) -> None:
        config = _config(domain="erp.example.com")
        with mock.patch.object(install, "choose", return_value="Let's Encrypt (managed externally)"), \
                mock.patch.object(install, "path_exists", return_value=True):
            self.assertEqual(install._maybe_plan_certs(config), [])
        self.assertEqual(config.tls_cert, "/etc/letsencrypt/live/erp.example.com/fullchain.pem")
        self.assertIn("ssl_certificate     /etc/letsencrypt/live/erp.example.com/fullchain.pem;",
                      planners._nginx_https_content(config, (1, 24, 0)))

    def test_no_certificate_means_no_https_plan(self) -> None:
        for mode in ("Let's Encrypt (managed externally)", 'Leave certificates untouched', ""):
            with mock.patch.object(install, "choose", return_value=mode), \
                    mock.patch.object(install, "path_exists", return_value=False):
                self.assertIsNone(install._maybe_plan_certs(_config()), mode)

    def test_untouched_keeps_the_files_the_vhost_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vhost = Path(tmp) / "shop-https.conf"
            vhost.write_text("server {\n  ssl_certificate /etc/letsencrypt/live/x/fullchain.pem;\n"
                             "  ssl_certificate_key /etc/letsencrypt/live/x/privkey.pem;\n}\n", encoding="utf-8")
            config = _config()
            real_open = open
            with mock.patch("builtins.open", lambda path, *a, **k: real_open(
                    vhost if str(path).endswith("shop-https.conf") else path, *a, **k)), \
                    mock.patch.object(install, "choose", return_value='Leave certificates untouched'), \
                    mock.patch.object(install, "path_exists", return_value=True):
                self.assertEqual(install._maybe_plan_certs(config), [])
        self.assertEqual((config.tls_cert, config.tls_key),
                         ("/etc/letsencrypt/live/x/fullchain.pem", "/etc/letsencrypt/live/x/privkey.pem"))

    def test_a_cancelled_file_pick_cancels(self) -> None:
        with mock.patch.object(install, "choose", return_value='Copy your own certificates (CRT/KEY[/Intermediate])'), \
                mock.patch.object(install, "select_file_path", return_value=""):
            self.assertIsNone(install._maybe_plan_certs(_config()))


class UfwGuardTests(unittest.TestCase):
    def test_ssh_rules_are_recognised(self) -> None:
        self.assertTrue(_allows_ssh("[ 1] 22/tcp                     ALLOW IN    Anywhere", [22]))
        self.assertTrue(_allows_ssh("[ 3] OpenSSH                    ALLOW IN    Anywhere", [2222]))
        self.assertTrue(_allows_ssh("[ 2] 2222/tcp (v6)              ALLOW IN    Anywhere (v6)", [2222]))
        self.assertFalse(_allows_ssh("[ 4] 443/tcp                    ALLOW IN    Anywhere", [22]))
        self.assertFalse(_allows_ssh("[ 5] Anywhere                   REJECT IN   203.0.113.7", [22]))


class StagedWriteTests(unittest.TestCase):
    def test_every_file_is_backed_up_before_any_is_written(self) -> None:
        script = planners.staged_files_command([("/a", "x", "644"), ("/b", "y", "644")], "true")
        lines = script.splitlines()
        last_backup = max(i for i, line in enumerate(lines) if '"$backup/' in line and line.startswith("if [ -e"))
        first_write = min(i for i, line in enumerate(lines) if line.startswith("cat > "))
        self.assertLess(last_backup, first_write)
        self.assertEqual(lines[0], "backup=$(mktemp -d) || exit 1")
        self.assertIn("trap 'fail Interrupted' INT TERM", script)


if __name__ == "__main__":
    unittest.main()
