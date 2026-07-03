---
type: how-to
title: "Interface language (Spanish / English)"
description: "Choose the UI language at startup or with the OIM_LANG environment variable."
tags: [i18n, language, ui]
audience: [operator]
updated: 2026-07-03
---

# Interface language

The tool's interface is available in **Spanish** (default) and **English**.

## Choosing the language

- **At startup** — when it starts, the tool asks **Español / English** (default Español), then shows the menu.
- **Non-interactively** — set the `OIM_LANG` environment variable to skip the prompt:

  ```bash
  OIM_LANG=en sudo -E python3 odoo_instance_manager.py   # English
  OIM_LANG=es sudo -E python3 odoo_instance_manager.py   # Spanish
  ```

  (Use `sudo -E` so the variable reaches the root process.)

## What is translated

Menus, prompts, section titles, table headers, and the plan preview render in the chosen language. Some
detailed status messages remain in Spanish for now — anything without a translation falls back to Spanish, so
nothing breaks. The translation catalog lives in `instance_manager/i18n.py` and is easy to extend.

## Related

- [Managing existing instances](operations/instance-management.md)
