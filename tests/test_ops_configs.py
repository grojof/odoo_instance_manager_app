"""nginx vhosts, fail2ban jails and UFW deletes: what the plans write."""

from __future__ import annotations

import unittest
from unittest import mock

from instance_manager import planners, system
from instance_manager.models import InstanceConfig
from instance_manager.workflows.firewall import _numbered_rule_line


def _config() -> InstanceConfig:
    return InstanceConfig(instance="shop", domain="shop.example.com")


class NginxTests(unittest.TestCase):
    def test_https_follows_odoos_guide(self) -> None:
        text = planners._nginx_https_content(_config(), (1, 24, 0))
        self.assertEqual(text.count('add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";'), 2)
        self.assertEqual(text.count("proxy_cookie_flags session_id samesite=lax secure;"), 2)
        self.assertIn("ssl_prefer_server_ciphers off;", text)
        self.assertIn("ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:", text)
        self.assertIn("ssl_session_timeout 30m;", text)
        self.assertIn("gzip on;", text)

    def test_cookie_flags_need_nginx_1_19_3(self) -> None:
        self.assertNotIn("proxy_cookie_flags", planners._nginx_https_content(_config(), (1, 19, 2)))
        self.assertIn("proxy_cookie_flags", planners._nginx_https_content(_config(), (1, 19, 3)))
        # Unknown: written as for an older nginx, which nginx -t accepts.
        self.assertNotIn("proxy_cookie_flags", planners._nginx_https_content(_config(), None))

    def test_http_allows_uploads_and_sends_no_hsts(self) -> None:
        text = planners._nginx_http_content(_config())
        self.assertIn("client_max_body_size 2048m;", text)
        self.assertNotIn("Strict-Transport-Security", text)

    def test_switch_validates_before_keeping(self) -> None:
        commands = planners.plan_nginx_https(_config(), (1, 24, 0))
        script = next(c.command for c in commands if "nginx -t" in c.command)
        self.assertLess(script.index("ln -sf"), script.index("nginx -t"))
        self.assertIn("fail 'nginx refused", script.split("nginx -t")[1])
        self.assertIn("trap 'fail Interrupted' INT TERM", script)
        self.assertFalse(any(c.command == "nginx -t" for c in commands))


class Fail2banTests(unittest.TestCase):
    def test_nginx_jails_only_with_nginx_logs(self) -> None:
        with_nginx = planners._fail2ban_base_content("127.0.0.1/8", "1h", "10m", 8, "24h", True)
        without = planners._fail2ban_base_content("127.0.0.1/8", "1h", "10m", 8, "24h", False)
        self.assertIn("[nginx-http-auth]", with_nginx)
        self.assertNotIn("[nginx-", without)

    def test_web_bans_are_scoped_and_recidive_uses_ufw(self) -> None:
        text = planners._fail2ban_base_content("127.0.0.1/8", "1h", "10m", 8, "24h", True)
        self.assertIn("banaction_allports = ufw", text)
        self.assertEqual(text.count("banaction = ufw-odoo-web"), 2)
        jail = planners._fail2ban_odoo_jail_content("odoo-auth-shop", "/var/log/odoo/shop.log", "1h", "10m", 8)
        self.assertIn("banaction = ufw-odoo-web", jail)
        # Only the web ports, with nothing fail2ban 0.11.2 would leave unquoted.
        self.assertIn("actionban = ufw prepend reject from <ip> to any port 80,443 proto tcp",
                      planners._fail2ban_web_action_content())

    def test_backend_is_never_set_for_every_jail(self) -> None:
        text = planners._fail2ban_base_content("127.0.0.1/8", "1h", "10m", 8, "24h", True)
        self.assertNotIn("backend", text.split("[sshd]")[0])
        self.assertNotIn("backend = systemd", text)
        journal = planners._fail2ban_base_content("127.0.0.1/8", "1h", "10m", 8, "24h", True, sshd_systemd=True)
        self.assertIn("[sshd]\nenabled = true\nbackend = systemd", journal)

    def test_typed_durations_and_networks(self) -> None:
        from instance_manager.workflows.fail2ban import _duration_error, _networks_error
        for good in ("10m", "1h", "1d", "2w", "1mo", "-1", "600"):
            self.assertIsNone(_duration_error(good), good)
        for bad in ("1 h", "1h\nenabled = false", "forever"):
            self.assertIsNotNone(_duration_error(bad), bad)
        self.assertIsNone(_networks_error("203.0.113.7, 10.0.0.0/8 2001:db8::/32"))
        self.assertIsNotNone(_networks_error("203.0.113.7\nignoreip = 0.0.0.0/0"))

    def test_filter_is_tested_on_every_versions_line(self) -> None:
        commands = planners.plan_fail2ban_enable_odoo_instance("shop", "/var/log/odoo/shop.log")
        test = next(c.command for c in commands if "fail2ban-regex" in c.command)
        for sample in planners.ODOO_LOGIN_FAILED_SAMPLES:
            self.assertIn(sample, test)
        self.assertIn("1 matched", test)

    def test_jails_are_written_through_a_validated_stage(self) -> None:
        for commands in (planners.plan_fail2ban_base_setup("127.0.0.1/8"),
                         planners.plan_fail2ban_enable_odoo_instance("shop", "/var/log/odoo/shop.log")):
            staged = next(c.command for c in commands if ".oim-new" in c.command)
            self.assertIn("fail2ban-client -t", staged)
            self.assertIn("restore", staged)


class StagedFilesTests(unittest.TestCase):
    def test_delimiter_never_collides(self) -> None:
        script = planners.staged_files_command([("/etc/x", "a\nOIM_EOF\nb", "644")], "true")
        self.assertIn("<<'OIM_EOF_1'", script)


class UfwTests(unittest.TestCase):
    STATUS = (
        "Status: active\n\n     To                         Action      From\n"
        "     --                         ------      ----\n"
        "[ 1] 22/tcp                     ALLOW IN    Anywhere\n"
        "[ 2] Anywhere                   REJECT IN   203.0.113.7               # by Fail2Ban\n"
        "[10] 8069/tcp                   ALLOW IN    Anywhere\n"
    )

    def test_rule_line_is_found_by_number(self) -> None:
        self.assertTrue(_numbered_rule_line(self.STATUS, 10).endswith("8069/tcp                   ALLOW IN    Anywhere"))
        self.assertIsNone(_numbered_rule_line(self.STATUS, 3))

    def test_delete_checks_the_rule_is_unchanged(self) -> None:
        line = _numbered_rule_line(self.STATUS, 1) or ""
        [command] = planners.plan_ufw_delete_rule(1, line)
        self.assertIn("grep -qxF --", command.command)
        self.assertLess(command.command.index("grep -qxF"), command.command.index("ufw --force delete 1"))

    def test_ssh_ports_from_sshd_and_socket(self) -> None:
        outputs = {"sshd -T 2>/dev/null": "port 2222\naddressfamily any\n",
                   "systemctl show -p Listen ssh.socket 2>/dev/null": "Listen=[::]:22 (Stream)\n"}

        def fake_run(cmd: str, check: bool = False):
            return mock.Mock(stdout=outputs.get(cmd, ""), returncode=0)

        with mock.patch.object(system, "run", fake_run):
            self.assertEqual(system.detect_ssh_ports(), [22, 2222])


if __name__ == "__main__":
    unittest.main()
