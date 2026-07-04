---
type: how-to
title: "Addon inventory"
description: "List an instance's addon modules by origin with versions, and which are installed."
tags: [addons, modules, inventory]
audience: [operator]
updated: 2026-07-03
---

# Addon inventory

From **Manage instances → Addon inventory**, the tool lists an instance's addon modules — read-only.

## What it shows

Modules are discovered under the instance's `addons_path` roots (from the `odoo.conf`, or the standard
`odoo/addons` + `addons-oca` + `addons-custom` layout) and grouped by **origin**, each its own table:

- **Odoo core** — the bundled Odoo modules (`…/odoo/addons`).
- **OCA** — community modules (`addons-oca`).
- **Custom** — your own modules (`addons-custom`).
- **Otros** — any other addons-path root.

Each module shows its **manifest version** (read from `__manifest__.py`, without executing it).

## Installed state (optional)

If you opt in and provide a database and credentials, each module is also marked with its **installed state**
and **installed version**, read from `ir_module_module`. A failed connection degrades gracefully to showing
only the available modules.

## Related

- [Managing existing instances](instance-management.md)
- [Installing and provisioning instances](../installation.md) — the `addons_path` layout.
