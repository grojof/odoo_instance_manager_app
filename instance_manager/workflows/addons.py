"""Inventory of an instance's addon modules: available (by origin) and installed."""

from __future__ import annotations

import ast
import datetime
import os
import re

from ..i18n import tf
from ..models import InstanceConfig
from ..prompts import ask_bool, ask_text
from ..system import read_odoo_conf, run
from ..ui import level_tag, level_text, render_table, strip_ansi, title
from .common import DbCredentials, _ask_db_credentials, _quote

_VERSION_RE = re.compile(r"""["']version["']\s*:\s*["']([^"']+)["']""")

# ir_module_module states that mean the module is currently on the system.
_INSTALLED_STATES = frozenset({"installed", "to upgrade", "to remove"})


def _is_installed(state: str) -> bool:
    return (state or "").strip() in _INSTALLED_STATES


def _build_group_rows(
    entries: list[tuple[str, str]],
    installed: dict[str, tuple[str, str]],
    only_installed: bool,
) -> list[list[str]]:
    """Rows [name, manifest version, state, installed version] for one origin group.
    When `only_installed`, modules whose state is not installed are dropped."""
    rows: list[list[str]] = []
    for name, version in entries:
        state, inst_version = installed.get(name, ("", ""))
        if only_installed and not _is_installed(state):
            continue
        rows.append([name, version, state or "-", inst_version or "-"])
    return rows


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
    return f"Other ({os.path.basename(lowered) or path})"


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


def _manifest_python_deps(manifest_text: str) -> list[str]:
    """The ``external_dependencies['python']`` list declared by a manifest, parsed
    as a literal (no code execution). A manifest that isn't a plain literal, or has
    no python deps, yields an empty list."""
    try:
        data = ast.literal_eval(manifest_text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return []
    if not isinstance(data, dict):
        return []
    external = data.get("external_dependencies")
    if not isinstance(external, dict):
        return []
    python = external.get("python")
    if isinstance(python, (list, tuple)):
        return [str(item) for item in python if isinstance(item, str) and item.strip()]
    return []


def _collect_python_deps(config: InstanceConfig) -> dict[str, set[str]]:
    """Map each declared Python package -> the set of addons that require it, across
    the instance's addons-path roots."""
    deps: dict[str, set[str]] = {}
    for root in _addon_roots(config):
        if not os.path.isdir(root):
            continue
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for name in entries:
            if name.startswith("."):
                continue
            for manifest in ("__manifest__.py", "__openerp__.py"):
                manifest_path = os.path.join(root, name, manifest)
                if not os.path.isfile(manifest_path):
                    continue
                try:
                    with open(manifest_path, encoding="utf-8", errors="replace") as handle:
                        for dep in _manifest_python_deps(handle.read()):
                            deps.setdefault(dep, set()).add(name)
                except OSError:
                    pass
                break
    return deps


def _venv_can_import(config: InstanceConfig, module: str) -> bool:
    """True if ``module`` imports in the instance venv (run as the instance user)."""
    if not re.fullmatch(r"[A-Za-z0-9_.]+", module):
        return False
    venv_python = f"{config.odoo_home}/venv/bin/python"
    cmd = (
        f"sudo -u {_quote(config.odoo_user)} {_quote(venv_python)} "
        f"-c {_quote('import ' + module)} >/dev/null 2>&1"
    )
    return run(cmd, check=False).returncode == 0


def _python_deps_audit_section(config: InstanceConfig) -> str | None:
    """Render the addons' required Python packages and whether each is installed in
    the instance venv. Returns the exportable section text, or None when none."""
    deps = _collect_python_deps(config)
    if not deps:
        print(level_text("INFO", 'No additional Python packages are declared by the addons.'))
        return None
    rows: list[list[str]] = []
    for module in sorted(deps):
        requiring = sorted(deps[module])
        sample = ", ".join(requiring[:3]) + (" …" if len(requiring) > 3 else "")
        state = "OK" if _venv_can_import(config, module) else "MISSING"
        rows.append([module, sample, level_tag(state)])
    heading = tf('Required Python packages (from addon manifests) — {}', config.instance)
    table = render_table(['Python package', 'Required by', 'In venv'], rows)
    print(f"\n{title(heading)}")
    print(table)
    return f"{heading}\n{strip_ansi(table)}"


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

    # Only offer the installed/all filter when a database was actually read.
    only_installed = bool(installed) and ask_bool('Show only installed modules (instead of all)?', True)

    # Odoo core first, then OCA, Custom, then the rest — each its own table.
    order = ["Odoo core", "OCA", "Custom"]
    groups = [g for g in order if g in grouped] + sorted(g for g in grouped if g not in order)
    sections: list[str] = []
    for group in groups:
        entries = sorted(set((name, version) for name, version, _root in grouped[group]))
        rows = _build_group_rows(entries, installed, only_installed)
        if not rows:
            continue
        heading = tf('{} — {} module(s)', group, len(rows))
        table = render_table(['Module', 'Version (manifest)', 'State', 'Installed version'], rows)
        print(f"\n{title(heading)}")
        print(table)
        sections.append(f"{heading}\n{strip_ansi(table)}")

    deps_section = _python_deps_audit_section(config)
    if deps_section:
        sections.append(deps_section)

    if not sections:
        print(level_text("INFO", 'No modules to show with the current filter.'))
        return

    _maybe_export_inventory(config, sections)


def _maybe_export_inventory(config: InstanceConfig, sections: list[str]) -> None:
    """Offer to export the rendered inventory to a text file, like the server-audit
    report export."""
    if not ask_bool('Export the inventory to a file?', True):
        print(level_text("INFO", 'Export skipped by the operator.'))
        return

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    default_path = f"./reports/addons_{config.instance}_{now}.txt"
    export_path = ask_text('Inventory export path', default_path, required=True)

    export_dir = os.path.dirname(export_path) or "."
    os.makedirs(export_dir, exist_ok=True)
    header = tf('Addon inventory: {}', config.instance)
    with open(export_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(f"{header}\n\n" + "\n\n".join(sections) + "\n")

    print(level_text("OK", tf('Inventory exported to: {}', export_path)))
