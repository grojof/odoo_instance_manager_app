# Design

Read-only inventory following the report pattern.

- **Roots** — `_addon_roots` reads `addons_path` from the conf (falling back to the standard
  `odoo/addons` + `addons-oca` + `addons-custom` layout).
- **Origin** — `_classify_addon_path` maps a root to "Odoo core" (`…/odoo/addons`, `…/odoo/odoo/addons`),
  "OCA" (`addons-oca`), "Custom" (`addons-custom`), or "Otros (<dir>)".
- **Modules + version** — `_modules_in_dir` lists subdirectories containing a `__manifest__.py`/`__openerp__.py`
  and extracts the version with a regex (`_extract_manifest_version`) — no manifest is executed.
- **Installed** — optional: `_installed_modules(creds, db)` runs
  `psql -tAF'|' -c "SELECT name, state, coalesce(latest_version,'') FROM ir_module_module"` and returns a
  name → (state, version) map; any error yields an empty map (graceful degrade).
- **Render** — one table per origin (Odoo core first, then OCA, Custom, others), columns
  Módulo · Versión (manifest) · Estado · Versión instalada.

## Testing

Pure helpers are unit-tested: version extraction (single/double quotes, missing), path classification, and
`_modules_in_dir` against a temp tree (manifest present/absent, dotfiles ignored). The DB enrichment and menu
are covered by operator acceptance.

## Out of scope

Installing/upgrading/uninstalling modules (inventory is read-only) — that stays an Odoo/CLI operation.
