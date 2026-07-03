# Add UI localization (Spanish / English)

## Why

The interface was Spanish-only. Users who prefer English (or non-Spanish-speaking operators) had no option, so
the tool wasn't approachable for a wider audience.

## What changes

A modular, efficient i18n layer that makes the interactive UI available in **Spanish or English**:

- **Language selection** at startup (a menu), or non-interactively via the `OIM_LANG` env var (`en`/`es`).
- **Translation at chokepoints**, not call sites: `title`, `prompt_label`, `level_text`, `choose` option
  display, table headers, and the plan-preview descriptions all pass their text through a `t()` catalog. Call
  sites are untouched, so this is a small, contained change.
- **`choose` returns the original** option (Spanish) while displaying the translation, so caller comparisons
  and behavior are language-independent.
- **Graceful fallback**: any string missing from the catalog shows in Spanish, so partial coverage degrades
  cleanly and the catalog can grow over time.

Scope: static UI strings (menus, prompts, titles, headers, plan descriptions) are translated; interpolated
detail messages (f-strings) fall back to Spanish for now.

## Impact

- New spec: `ui-localization`.
- New code: `instance_manager/i18n.py` (`t` / `set_language` / catalog); translation wired into `ui`, `prompts`,
  `system.preview_commands`, and the startup flow in `odoo_instance_manager.py`.
- New unit tests. stdlib only — no new dependency (no gettext/.mo files).
