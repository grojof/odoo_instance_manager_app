---
type: how-to
title: "Interface language (English / Spanish)"
description: "Choose the UI language at startup or with the OIM_LANG environment variable."
tags: [i18n, language, ui]
audience: [operator]
updated: 2026-07-04
---

# Interface language

The tool's interface is available in **English** (default) and **Spanish**. English is the source
language: the strings live in English in the code, and Spanish is a full translation applied on demand.

## Choosing the language

- **At startup** — when it starts, the tool asks **Español / English**, then shows the menu.
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
nothing breaks. The translation catalog lives in `instance_manager/i18n.py` and is easy to extend.

## Related

- [Managing existing instances](operations/instance-management.md)
