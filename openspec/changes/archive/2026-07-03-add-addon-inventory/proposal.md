# Add addon inventory

## Why

Operators need to know which addon modules an instance actually ships beyond Odoo's bundled core (OCA, custom),
at what version, and which are installed in a given database — today that means poking around the filesystem
and the DB by hand.

## What changes

A new **addon-inventory** capability, from *Gestionar instancias → Inventario de addons*:

- Discover modules under the instance's `addons_path` roots, group them by origin (**Odoo core** / **OCA** /
  **Custom** / other), and show each module's **manifest version**.
- Optionally connect to a database and mark which modules are **installed** and their installed version
  (from `ir_module_module`); a failed connection degrades to showing only what's available.

Read-only; each origin is its own table so core and the rest are clearly separated.

## Impact

- New spec: `addon-inventory`.
- New code: `workflows/addons.py` (`show_addon_inventory` + pure helpers), wired into `manage_existing_instance`.
- New unit tests (manifest-version parse, path classification, module listing). No new dependency.
