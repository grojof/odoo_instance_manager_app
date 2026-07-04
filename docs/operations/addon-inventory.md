---
type: how-to
title: "Addon inventory"
description: "List an instance's addon modules by origin with versions, and which are installed."
tags: [addons, modules, inventory]
audience: [operator]
updated: 2026-07-04
---

# Addon inventory

From **Manage instances → Addon inventory**, the tool lists an instance's addon modules — read-only.

## What it shows

Modules are discovered under the instance's `addons_path` roots (from the `odoo.conf`, or the standard
`odoo/addons` + `addons-oca` + `addons-custom` layout) and grouped by **origin**, each its own table:

- **Odoo core** — the bundled Odoo modules (`…/odoo/addons`).
- **OCA** — community modules (`addons-oca`).
- **Custom** — your own modules (`addons-custom`).
- **Other** — any other addons-path root.

Each module shows its **manifest version** (read from `__manifest__.py`, without executing it).

## Installed state (optional)

If you opt in and provide a database and credentials, each module is also marked with its **installed state**
and **installed version**, read from `ir_module_module`. A failed connection degrades gracefully to showing
only the available modules.

## Required Python packages

The inventory also audits the **Python packages the addons declare** via each manifest's
`external_dependencies['python']` (read safely as a literal, no code execution). For each declared package it
shows which addons require it and whether it **imports in the instance venv** (`OK` / `MISSING`) — so you can
spot addon dependencies that aren't installed yet (a common cause of errors, e.g. after duplicating an
instance). This audit is included in the export.

## Show only installed, or all

After checking a database, the tool asks **"Show only installed modules (instead of all)?"** (default yes) —
handy because the full list is long. Only-installed hides not-installed modules and any origin group left
empty; choose *no* to keep the complete inventory.

## Export (optional)

After the tables are shown, you can **export the inventory to a text file** (default under `./reports/`),
mirroring the [server audit](../server-audit.md) export. The file reflects the active installed/all filter.
Declining writes nothing.

## Related

- [Managing existing instances](instance-management.md)
- [Installing and provisioning instances](../installation.md) — the `addons_path` layout.
