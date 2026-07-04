"""Tests for the addon-inventory helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from instance_manager.workflows.addons import (
    _build_group_rows,
    _classify_addon_path,
    _extract_manifest_version,
    _is_installed,
    _manifest_python_deps,
    _modules_in_dir,
)


class ManifestPythonDepsTests(unittest.TestCase):
    def test_extracts_python_external_dependencies(self) -> None:
        manifest = "{'name': 'x', 'external_dependencies': {'python': ['ldap', 'stripe'], 'bin': ['wkhtmltopdf']}}"
        self.assertEqual(_manifest_python_deps(manifest), ["ldap", "stripe"])

    def test_no_external_dependencies(self) -> None:
        self.assertEqual(_manifest_python_deps("{'name': 'x'}"), [])

    def test_malformed_manifest_is_skipped(self) -> None:
        self.assertEqual(_manifest_python_deps("{'name': undefined_func()}"), [])

    def test_non_dict_manifest_is_empty(self) -> None:
        self.assertEqual(_manifest_python_deps("[1, 2, 3]"), [])


class ManifestVersionTests(unittest.TestCase):
    def test_extracts_version(self) -> None:
        self.assertEqual(_extract_manifest_version("{'version': '16.0.1.2.0', 'name': 'x'}"), "16.0.1.2.0")

    def test_double_quotes(self) -> None:
        self.assertEqual(_extract_manifest_version('{"version": "1.0"}'), "1.0")

    def test_missing_version(self) -> None:
        self.assertEqual(_extract_manifest_version("{'name': 'x'}"), "?")


class InstalledFilterTests(unittest.TestCase):
    def test_is_installed_states(self) -> None:
        for state in ("installed", "to upgrade", "to remove"):
            self.assertTrue(_is_installed(state))
        for state in ("uninstalled", "to install", "uninstallable", ""):
            self.assertFalse(_is_installed(state))

    def test_all_rows_when_not_filtering(self) -> None:
        entries = [("sale", "18.0"), ("stock", "18.0")]
        installed = {"sale": ("installed", "18.0.1")}
        rows = _build_group_rows(entries, installed, only_installed=False)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["sale", "18.0", "installed", "18.0.1"])
        self.assertEqual(rows[1], ["stock", "18.0", "-", "-"])

    def test_only_installed_filters_out_the_rest(self) -> None:
        entries = [("sale", "18.0"), ("stock", "18.0"), ("mrp", "18.0")]
        installed = {"sale": ("installed", "18.0.1"), "stock": ("uninstalled", "")}
        rows = _build_group_rows(entries, installed, only_installed=True)
        self.assertEqual([r[0] for r in rows], ["sale"])


class ClassifyAddonPathTests(unittest.TestCase):
    def test_known_origins(self) -> None:
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/odoo/addons"), "Odoo core")
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/odoo/odoo/addons"), "Odoo core")
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/addons-oca"), "OCA")
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/addons-custom"), "Custom")

    def test_unknown_origin_is_labelled(self) -> None:
        self.assertTrue(_classify_addon_path("/opt/odoo/inst/extra-mods").startswith("Other"))


class ModulesInDirTests(unittest.TestCase):
    def test_lists_modules_with_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod_a").mkdir()
            (root / "mod_a" / "__manifest__.py").write_text("{'version': '1.2.3'}", encoding="utf-8")
            (root / "mod_b").mkdir()
            (root / "mod_b" / "__openerp__.py").write_text("{'version': '9.0.1'}", encoding="utf-8")
            (root / "not_a_module").mkdir()  # no manifest -> ignored
            (root / ".hidden").mkdir()
            result = dict(_modules_in_dir(str(root)))
        self.assertEqual(result, {"mod_a": "1.2.3", "mod_b": "9.0.1"})

    def test_missing_dir_is_empty(self) -> None:
        self.assertEqual(_modules_in_dir("/no/such/dir"), [])


if __name__ == "__main__":
    unittest.main()
