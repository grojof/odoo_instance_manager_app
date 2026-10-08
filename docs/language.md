---
type: how-to
title: "Interface language (English / Spanish)"
description: "Choose the UI language at startup or with the OIM_LANG environment variable."
tags: [i18n, language, ui]
audience: [operator]
updated: 2026-10-08
---

# Interface language

The tool's interface is available in **English** (default) and **Spanish**. English is the source
language: the strings live in English in the code, and Spanish is a full translation applied on demand.

## Choosing the language

- **At startup** — the tool asks **Idioma / Language** (English is the default), then shows the menu.
- **Non-interactively** — set the `OIM_LANG` environment variable to skip the prompt:

  ```bash
  OIM_LANG=en sudo -E python3 odoo_instance_manager.py   # English
  OIM_LANG=es sudo -E python3 odoo_instance_manager.py   # Spanish
  ```

  (Use `sudo -E` so the variable reaches the root process.)

## What is translated

Everything user-facing renders in the chosen language: menus, prompts, section titles, table headers and
string cells, command/plan descriptions, interpolated status messages, and the yes/no shortcut (`Y/n` in
English, `S/n` in Spanish). Anything without a Spanish translation falls back to its English source, so
nothing breaks. The catalog lives in `instance_manager/i18n.py`, English → Spanish; a test fails when an interface string has
no Spanish entry.

## Related

- [Managing existing instances](operations/instance-management.md)
