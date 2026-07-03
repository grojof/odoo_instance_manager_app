# Design

## Why a chokepoint catalog (not gettext, not per-call-site keys)

The UI has hundreds of Spanish string literals across ~15 modules. Two common approaches were rejected:

- **gettext / .po/.mo** — adds a build step and binary catalogs, and still needs every string wrapped.
- **Per-call-site keys** (`t("menu.services")`) — a massive, risky edit of every call site.

Instead, translation happens at the few **display/input chokepoints** every string already flows through, with
the **Spanish source string as the key**. This needs no call-site changes and no build step; it is pure stdlib.

## Chokepoints

- `ui.title`, `ui.prompt_label`, `ui.level_text` — translate their text/message.
- `ui.render_table` — translate the **headers** only (rows are data).
- `prompts.choose` — display `t(option)` but **return the original** option, so caller comparisons
  (`if action == "Servicios instancias"`) and behavior are language-independent.
- `system.preview_commands` — translate each `Command` description.

`i18n` holds module state (`_LANG`), `set_language`/`current_language`, `t(text)`, and the `_EN` catalog
(Spanish → English). `i18n` imports nothing from the package, so there is no cycle.

## Selection

`odoo_instance_manager._select_language()` reads `OIM_LANG` (`en`/`es`) or asks via `choose` (default Español)
before the main menu.

## Known limitation

Interpolated messages (f-strings like `f"Ya existe {path}"`) are formatted before reaching a chokepoint, so
they don't match a catalog key and stay Spanish. Static UI (menus, prompts, titles, headers, plan descriptions)
is translated. New static strings translate by adding one catalog entry; interpolated strings would need a
placeholder-keyed catalog, out of scope here.

## Testing

`tests/test_i18n.py`: `t` is identity in Spanish, translates/falls-back in English, `set_language` normalizes,
table headers translate while rows don't, and `choose` shows the translation yet returns the original.
