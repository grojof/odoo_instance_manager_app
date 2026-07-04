from __future__ import annotations

import unittest

from instance_manager.models import InstanceConfig
from instance_manager.planners import (
    _https_listen_block,
    _odoo_conf_content,
    compute_worker_tuning,
    plan_install_wkhtmltopdf,
    posture_rows,
    resolve_wkhtmltopdf_asset,
)


class WorkerTuningTests(unittest.TestCase):
    def test_formula_when_ram_is_ample(self) -> None:
        # 4 CPU -> (4*2)+1 = 9 workers, uncapped by 64 GiB RAM.
        tuning = compute_worker_tuning(4, 64 * 1024**3)
        self.assertEqual(tuning["workers"], 9)
        self.assertEqual(tuning["max_cron_threads"], 2)
        self.assertEqual(tuning["limit_request"], 8192)

    def test_capped_by_low_ram(self) -> None:
        # 8 CPU would suggest 17, but 4 GiB RAM caps it well below that.
        tuning = compute_worker_tuning(8, 4 * 1024**3)
        self.assertLess(tuning["workers"], 17)
        self.assertGreaterEqual(tuning["workers"], 2)

    def test_floor_of_two(self) -> None:
        tuning = compute_worker_tuning(1, 1 * 1024**3)
        self.assertGreaterEqual(tuning["workers"], 2)


class OdooConfRenderingTests(unittest.TestCase):
    def _conf(self, **kwargs) -> str:
        base = dict(
            instance="shop",
            db_password="x",
            odoo_admin_passwd="y",
        )
        base.update(kwargs)
        return _odoo_conf_content(InstanceConfig(**base))

    def test_modern_odoo_uses_gevent_port(self) -> None:
        conf = self._conf(version="18")
        self.assertIn("gevent_port = 8072", conf)
        self.assertNotIn("longpolling_port", conf)

    def test_legacy_odoo_uses_longpolling_port(self) -> None:
        conf = self._conf(version="15")
        self.assertIn("longpolling_port = 8072", conf)
        self.assertNotIn("gevent_port", conf)

    def test_dbfilter_written_when_set(self) -> None:
        conf = self._conf(list_db=False, dbfilter="^shop$")
        self.assertIn("list_db = False", conf)
        self.assertIn("dbfilter = ^shop$", conf)

    def test_dbfilter_omitted_when_blank(self) -> None:
        # A blank dbfilter means "no filtering" — the key must not be written,
        # even when a DB name is known.
        conf = self._conf(list_db=False, db_name="shop")
        self.assertNotIn("dbfilter", conf)

    def test_suggested_dbfilter(self) -> None:
        self.assertEqual(
            InstanceConfig(instance="x", db_name="shop").suggested_dbfilter(), "^shop$"
        )
        self.assertEqual(InstanceConfig(instance="x").suggested_dbfilter(), "^%d$")

    def test_db_sslmode_only_for_remote_host(self) -> None:
        local = self._conf(db_host="127.0.0.1", db_sslmode="require")
        self.assertNotIn("db_sslmode", local)
        remote = self._conf(db_host="10.0.0.5", db_sslmode="require")
        self.assertIn("db_sslmode = require", remote)


class NginxHttp2Tests(unittest.TestCase):
    def test_old_nginx_uses_listen_http2(self) -> None:
        self.assertIn("ssl http2", _https_listen_block((1, 24, 0)))
        self.assertNotIn("http2 on", _https_listen_block((1, 24, 0)))

    def test_new_nginx_uses_http2_directive(self) -> None:
        block = _https_listen_block((1, 25, 1))
        self.assertIn("http2 on;", block)
        self.assertNotIn("ssl http2", block)

    def test_unknown_nginx_falls_back_to_old_form(self) -> None:
        self.assertIn("ssl http2", _https_listen_block(None))


class WkhtmltopdfResolverTests(unittest.TestCase):
    def test_ubuntu_codenames_map_to_jammy_asset(self) -> None:
        for codename in ("jammy", "noble"):
            asset = resolve_wkhtmltopdf_asset(codename)
            self.assertIsNotNone(asset)
            self.assertIn("jammy", asset[1])

    def test_unmapped_codename_returns_none(self) -> None:
        self.assertIsNone(resolve_wkhtmltopdf_asset("focal"))
        self.assertIsNone(resolve_wkhtmltopdf_asset(""))

    def test_patched_plan_has_checksum_gate(self) -> None:
        commands = plan_install_wkhtmltopdf("patched", "noble")
        joined = " ".join(command.command for command in commands)
        self.assertIn("sha256sum -c", joined)

    def test_unmapped_patched_plan_is_empty(self) -> None:
        self.assertEqual(plan_install_wkhtmltopdf("patched", "focal"), [])

    def test_distro_plan_installs_apt_package(self) -> None:
        commands = plan_install_wkhtmltopdf("distro")
        self.assertTrue(any("install wkhtmltopdf" in c.command for c in commands))


class PostureTests(unittest.TestCase):
    def test_flags_weak_and_exposed(self) -> None:
        conf = {
            "list_db": "True",
            "admin_passwd": "shop",
            "db_password": "shop",
            "proxy_mode": "True",
            "db_host": "127.0.0.1",
            "workers": "4",
        }
        states = {check: state for state, check, _ in posture_rows(
            instance="shop", conf_values=conf, wkhtmltopdf_ver=None, cpu_count=2
        )}
        self.assertEqual(states["Database manager (list_db)"], "WARN")
        self.assertEqual(states["Master password (admin_passwd)"], "WARN")
        self.assertEqual(states["wkhtmltopdf"], "WARN")

    def test_hashed_master_password_is_ok(self) -> None:
        conf = {"admin_passwd": "$pbkdf2-sha512$abc", "list_db": "False"}
        states = {check: state for state, check, _ in posture_rows(
            instance="shop", conf_values=conf, wkhtmltopdf_ver="wkhtmltopdf 0.12.6 (with patched qt)", cpu_count=2
        )}
        self.assertEqual(states["Master password (admin_passwd)"], "OK")
        self.assertEqual(states["Database manager (list_db)"], "OK")
        self.assertEqual(states["wkhtmltopdf"], "OK")

    def test_remote_db_without_sslmode_warns(self) -> None:
        conf = {"db_host": "10.0.0.5", "list_db": "False"}
        states = {check: state for state, check, _ in posture_rows(
            instance="shop", conf_values=conf, wkhtmltopdf_ver=None, cpu_count=2
        )}
        self.assertEqual(states["db_sslmode (remote DB)"], "WARN")


if __name__ == "__main__":
    unittest.main()
