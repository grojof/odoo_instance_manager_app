"""Per-version install facts: interpreter, setuptools, core, odoo.conf, unit, update."""

from __future__ import annotations

import unittest

from instance_manager import support
from instance_manager.models import InstanceConfig
from instance_manager.planners import (
    _odoo_conf_content,
    _systemd_content,
    _venv_commands,
    plan_db_setup,
    plan_ensure_uv,
    plan_odoo_base_setup,
    plan_update_instance_config,
    render_merged_odoo_conf,
)


def _config(version: str = "18", **kw: object) -> InstanceConfig:
    config = InstanceConfig(instance="shop", version=version, repo_branch=f"{version}.0", **kw)  # type: ignore[arg-type]
    config.db_password = "pw"
    config.odoo_admin_passwd = "master"
    config.normalize_defaults()
    return config


class InterpreterChoiceTests(unittest.TestCase):
    def test_host_python_is_used_inside_the_range(self) -> None:
        for major in (15, 16, 17, 18, 19):
            self.assertEqual(support.choose_python(support.ODOO_SUPPORT[major], "3.12"), ("3.12", support.HOST))

    def test_out_of_range_host_gets_uv(self) -> None:
        # Odoo 14 declares Python up to 3.10: Ubuntu 24.04's 3.12 cannot build it.
        self.assertEqual(support.choose_python(support.ODOO_SUPPORT[14], "3.12"), ("3.8", support.UV))
        # Odoo 17-19 need 3.10 at least: Debian 11's 3.9 is too old.
        self.assertEqual(support.choose_python(support.ODOO_SUPPORT[17], "3.9"), ("3.12", support.UV))

    def test_unbounded_versions_stop_at_the_recommendation(self) -> None:
        # 12/13 state no maximum, yet their gevent does not build on 3.12.
        self.assertEqual(support.choose_python(support.ODOO_SUPPORT[12], "3.12")[1], support.UV)
        self.assertEqual(support.choose_python(support.ODOO_SUPPORT[13], "3.8"), ("3.8", support.HOST))

    def test_the_gevent_2108_rows_are_avoided(self) -> None:
        # Each branch's requirements.txt pins gevent==21.8.0, which pip cannot build,
        # for: 14 > 3.9, 15 3.10-3.11, 16-19 3.10.
        for major, python, expected in ((14, "3.10", ("3.8", support.UV)), (15, "3.10", ("3.12", support.UV)),
                                        (15, "3.11", ("3.12", support.UV)), (16, "3.10", ("3.12", support.UV)),
                                        (19, "3.10", ("3.12", support.UV)), (15, "3.12", ("3.12", support.HOST)),
                                        (16, "3.11", ("3.11", support.HOST))):
            with self.subTest(major=major, python=python):
                self.assertEqual(support.choose_python(support.ODOO_SUPPORT[major], python), expected)

    def test_odoo_states_the_maximum_from_15(self) -> None:
        # MAX_PY_VERSION in odoo/__init__.py (15.0-18.0) and odoo/release.py (19.0).
        for major, maximum in ((15, "3.12"), (16, "3.12"), (17, "3.14"), (18, "3.14"), (19, "3.14")):
            with self.subTest(major=major):
                self.assertEqual(support.ODOO_SUPPORT[major].python_max, maximum)
                self.assertEqual(support.ODOO_SUPPORT[major].python_max_tier, support.OFFICIAL)
        # Debian 13's 3.13 is outside 16's range: uv's 3.12.
        self.assertEqual(support.choose_python(support.ODOO_SUPPORT[16], "3.13"), ("3.12", support.UV))

    def test_no_host_python_gets_uv(self) -> None:
        self.assertEqual(support.choose_python(support.ODOO_SUPPORT[18], None)[1], support.UV)

    def test_every_recommendation_is_inside_its_range(self) -> None:
        for major, version in support.ODOO_SUPPORT.items():
            with self.subTest(major=major):
                self.assertTrue(support.python_in_range(version, version.recommended_python))


class SetuptoolsTests(unittest.TestCase):
    def test_pins_follow_the_version(self) -> None:
        self.assertEqual(support.setuptools_requirement(12), "setuptools<58")
        self.assertEqual(support.setuptools_requirement(13), "setuptools<58")
        self.assertEqual(support.setuptools_requirement(16), "setuptools<81")
        self.assertEqual(support.setuptools_requirement(17), "setuptools")

    def test_venv_installs_the_pin_and_never_bare_setuptools_for_16(self) -> None:
        text = "\n".join(c.command for c in _venv_commands(_config("16")))
        self.assertIn("'setuptools<81'", text)
        self.assertNotIn("wheel setuptools", text)


class VenvTests(unittest.TestCase):
    def test_uv_interpreter_is_used_when_chosen(self) -> None:
        config = _config("14", python="3.8", python_source=support.UV)
        text = "\n".join(c.command for c in _venv_commands(config))
        self.assertIn("uv venv --seed --allow-existing --no-project --python 3.8", text)
        self.assertIn(f"UV_PYTHON_INSTALL_DIR={support.UV_PYTHON_DIR}", text)
        self.assertIn("UV_PYTHON_DOWNLOADS=never", text)
        self.assertIn("sudo -u shop -H bash -c", text)

    def test_host_interpreter_by_default(self) -> None:
        text = "\n".join(c.command for c in _venv_commands(_config("18")))
        self.assertIn("python3 -m venv /opt/odoo/shop/venv", text)

    def test_odoo_12_replaces_pyldap(self) -> None:
        text = "\n".join(c.command for c in _venv_commands(_config("12")))
        self.assertIn("grep -v -i -E", text)
        self.assertIn("python-ldap==3.1.0", text)


class CoreTests(unittest.TestCase):
    def test_ocb_is_cloned_from_oca(self) -> None:
        text = "\n".join(c.command for c in plan_odoo_base_setup(_config("18", core="ocb")))
        self.assertIn("https://github.com/OCA/OCB.git", text)
        self.assertNotIn("github.com/odoo/odoo.git", text)

    def test_official_by_default(self) -> None:
        text = "\n".join(c.command for c in plan_odoo_base_setup(_config("18")))
        self.assertIn("https://github.com/odoo/odoo.git", text)

    def test_unknown_core_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            plan_odoo_base_setup(_config("18", core="fork"))


class OdooConfTests(unittest.TestCase):
    def test_demo_is_off_up_to_18(self) -> None:
        self.assertIn("without_demo = all", _odoo_conf_content(_config("18")))
        self.assertIn("without_demo = all", _odoo_conf_content(_config("14")))
        # 19 loads no demo data unless --with-demo.
        self.assertNotIn("without_demo", _odoo_conf_content(_config("19")))

    def test_data_dir_is_written_when_set(self) -> None:
        config = _config("18")
        self.assertNotIn("data_dir", _odoo_conf_content(config))
        config.data_dir = config.managed_data_dir
        self.assertIn("data_dir = /var/lib/odoo/shop", _odoo_conf_content(config))

    def test_base_setup_creates_the_data_dir_for_the_user(self) -> None:
        config = _config("18")
        config.data_dir = config.managed_data_dir
        text = "\n".join(c.command for c in plan_odoo_base_setup(config))
        self.assertIn("install -d -m 750 -o shop -g shop /var/lib/odoo/shop", text)


class SystemdTests(unittest.TestCase):
    def test_unit_matches_odoos_own_and_waits_for_a_local_db(self) -> None:
        unit = _systemd_content(_config("18"))
        self.assertIn("KillMode=mixed", unit)
        self.assertIn("After=network-online.target postgresql.service", unit)
        remote = _config("18")
        remote.db_host = "db.example.com"
        self.assertIn("After=network-online.target\n", _systemd_content(remote))


class PostgresFloorTests(unittest.TestCase):
    def test_floor_is_checked(self) -> None:
        text = "\n".join(c.command for c in plan_db_setup(_config("19"), ensure_remote_access=False))
        self.assertIn('[ "$v" -ge 130000 ]', text)
        text = "\n".join(c.command for c in plan_db_setup(_config("18"), ensure_remote_access=False))
        self.assertIn('[ "$v" -ge 120000 ]', text)

    def test_local_install_opens_nothing(self) -> None:
        text = "\n".join(c.command for c in plan_db_setup(_config("18"), ensure_remote_access=False))
        self.assertNotIn("listen_addresses", text)
        self.assertNotIn("pg_hba", text.lower().replace("show hba_file", ""))


class UvTests(unittest.TestCase):
    def test_uv_is_checksum_verified(self) -> None:
        text = "\n".join(c.command for c in plan_ensure_uv("x86_64"))
        filename, sha256 = support.UV_ASSETS["x86_64"]
        self.assertIn(f"releases/download/{support.UV_VERSION}/{filename}", text)
        self.assertIn(sha256, text)
        self.assertIn("sha256sum -c -", text)

    def test_unknown_architecture_plans_nothing(self) -> None:
        self.assertEqual(plan_ensure_uv("riscv64"), [])


class UpdateConfigTests(unittest.TestCase):
    EXISTING = {
        "admin_passwd": "old",
        "addons_path": "/opt/odoo/shop/odoo/addons,/opt/odoo/shop/addons-oca/web",
        "data_dir": "/srv/odoo-data",
        "smtp_server": "mail.example.com",
        "server_wide_modules": "base,web,queue_job",
        "longpolling_port": "8072",
        "workers": "4",
    }

    def test_merge_keeps_tuned_and_unknown_keys(self) -> None:
        config = _config("18")
        merged = render_merged_odoo_conf(config, self.EXISTING)
        self.assertIn("addons_path = /opt/odoo/shop/odoo/addons,/opt/odoo/shop/addons-oca/web", merged)
        self.assertIn("data_dir = /srv/odoo-data", merged)
        self.assertIn("smtp_server = mail.example.com", merged)
        self.assertIn("server_wide_modules = base,web,queue_job", merged)
        # The tool's own keys take the new value; the old bus key is not duplicated.
        self.assertIn("admin_passwd = master", merged)
        self.assertNotIn("longpolling_port", merged)
        self.assertEqual(merged.count("addons_path ="), 1)

    def test_update_reinstalls_nothing_and_restarts(self) -> None:
        commands = plan_update_instance_config(_config("16"), self.EXISTING, new_db_password=True, restart=True)
        text = "\n".join(c.command for c in commands)
        for absent in ("apt-get", "git clone", "pip install"):
            self.assertNotIn(absent, text)
        alter = next(c for c in commands if "OIM_SQL" in c.command)
        self.assertEqual(alter.env["OIM_SQL"],
                         "SET password_encryption = 'scram-sha-256'; ALTER ROLE \"shop\" WITH PASSWORD 'pw';")
        # The password is in no command text and the preview masks it.
        self.assertNotIn("'pw'", text)
        self.assertNotIn("'pw'", "\n".join(c.shown for c in commands))
        self.assertIn("systemctl restart shop", text)

    def test_no_password_change_no_role_change(self) -> None:
        commands = plan_update_instance_config(_config("18"), {}, new_db_password=False, restart=False)
        text = "\n".join(c.command for c in commands)
        self.assertNotIn("ALTER ROLE", text)
        self.assertNotIn("systemctl restart", text)


if __name__ == "__main__":
    unittest.main()
