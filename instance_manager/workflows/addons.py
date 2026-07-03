"""Inventory of an instance's addon modules: available (by origin) and installed."""

from __future__ import annotations

import os
import re

from ..i18n import tf
from ..models import InstanceConfig
from ..prompts import ask_bool, ask_text
from ..system import read_odoo_conf, run
from ..ui import level_text, render_table, title
from .common import DbCredentials, _ask_db_credentials, _quote

_VERSION_RE = re.compile(r"""["']version["']\s*:\s*["']([^"']+)["']""")


def _extract_manifest_version(manifest_text: str) -> str:
    match = _VERSION_RE.search(manifest_text)
    return match.group(1) if match else "?"


def _classify_addon_path(path: str) -> str:
    lowered = path.rstrip("/").lower()
    if lowered.endswith("/odoo/addons") or lowered.endswith("/odoo/odoo/addons"):
        return "Odoo core"
    if lowered.endswith("addons-oca") or "/addons-oca" in lowered:
        return "OCA"
    if lowered.endswith("addons-custom") or "/addons-custom" in lowered:
        return "Custom"
    return f"Otros ({os.path.basename(lowered) or path})"


def _addon_roots(config: InstanceConfig) -> list[str]:
    conf = read_odoo_conf(config.odoo_conf_file)
    addons_path = conf.get("addons_path", "").strip()
    if addons_path:
        roots = [part.strip() for part in addons_path.split(",") if part.strip()]
    else:
        roots = [
            f"{config.odoo_home}/odoo/addons",
            f"{config.odoo_home}/addons-oca",
            f"{config.odoo_home}/addons-custom",
        ]
    return roots


def _modules_in_dir(path: str) -> list[tuple[str, str]]:
    """Return (module_name, manifest_version) for each module dir under `path`."""
    modules: list[tuple[str, str]] = []
    if not os.path.isdir(path):
        return modules
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return modules
    for name in entries:
        if name.startswith("."):
            continue
        for manifest in ("__manifest__.py", "__openerp__.py"):
            manifest_path = os.path.join(path, name, manifest)
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8", errors="replace") as handle:
                        version = _extract_manifest_version(handle.read())
                except OSError:
                    version = "?"
                modules.append((name, version))
                break
    return modules


def _installed_modules(creds: DbCredentials, db_name: str) -> dict[str, tuple[str, str]]:
    """name -> (state, installed_version) from ir_module_module, or empty on error."""
    sql = "SELECT name, state, coalesce(latest_version, '') FROM ir_module_module"
    cmd = (
        f"PGPASSWORD={_quote(creds.password)} psql -h {_quote(creds.host)} -p {creds.port} "
        f"-U {_quote(creds.user)} -d {_quote(db_name)} -tAF'|' -c {_quote(sql)}"
    )
    result = run(cmd, check=False)
    installed: dict[str, tuple[str, str]] = {}
    if result.returncode != 0:
        return installed
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            installed[parts[0]] = (parts[1], parts[2])
    return installed


def show_addon_inventory(config: InstanceConfig) -> None:
    print(f"\n{title(tf('Addon inventory: {}', config.instance))}")
    roots = _addon_roots(config)

    grouped: dict[str, list[tuple[str, str, str]]] = {}
    for root in roots:
        group = _classify_addon_path(root)
        for name, version in _modules_in_dir(root):
            grouped.setdefault(group, []).append((name, version, root))

    if not grouped:
        print(level_text("WARN", 'No modules found in the addons paths.'))
        return

    installed: dict[str, tuple[str, str]] = {}
    if ask_bool('Check which modules are installed in a database?', False):
        db_name = ask_text('Database to inspect', config.db_name or config.instance, required=True)
        creds = _ask_db_credentials(config.instance, None)
        installed = _installed_modules(creds, db_name)
        if not installed:
            print(level_text("WARN", "Could not read ir_module_module (connection/DB); showing only what's available."))

    # Odoo core first, then OCA, Custom, then the rest — each its own table.
    order = ["Odoo core", "OCA", "Custom"]
    groups = [g for g in order if g in grouped] + sorted(g for g in grouped if g not in order)
    for group in groups:
        entries = sorted(set((name, version) for name, version, _root in grouped[group]))
        rows: list[list[str]] = []
        for name, version in entries:
            state, inst_version = installed.get(name, ("", ""))
            rows.append([name, version, state or "-", inst_version or "-"])
        print(f"\n{title(tf('{} — {} module(s)', group, len(rows)))}")
        print(render_table(['Module', 'Version (manifest)', 'State', 'Installed version'], rows))
