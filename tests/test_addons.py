"""Tests for the addon-inventory helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from instance_manager.workflows.addons import (
    _classify_addon_path,
    _extract_manifest_version,
    _modules_in_dir,
)


class ManifestVersionTests(unittest.TestCase):
    def test_extracts_version(self) -> None:
        self.assertEqual(_extract_manifest_version("{'version': '16.0.1.2.0', 'name': 'x'}"), "16.0.1.2.0")

    def test_double_quotes(self) -> None:
        self.assertEqual(_extract_manifest_version('{"version": "1.0"}'), "1.0")

    def test_missing_version(self) -> None:
        self.assertEqual(_extract_manifest_version("{'name': 'x'}"), "?")


class ClassifyAddonPathTests(unittest.TestCase):
    def test_known_origins(self) -> None:
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/odoo/addons"), "Odoo core")
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/odoo/odoo/addons"), "Odoo core")
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/addons-oca"), "OCA")
        self.assertEqual(_classify_addon_path("/opt/odoo/inst/addons-custom"), "Custom")

    def test_unknown_origin_is_labelled(self) -> None:
        self.assertTrue(_classify_addon_path("/opt/odoo/inst/extra-mods").startswith("Otros"))


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
