# Tasks

- [x] 1.1 Add `instance_manager/i18n.py` (`t` / `set_language` / `current_language` + Spanish→English catalog).
- [x] 1.2 Wire translation into `ui.title/prompt_label/level_text`, `render_table` headers, `prompts.choose`
  (display-only; return original), and `system.preview_commands` descriptions.
- [x] 1.3 Add startup language selection (`OIM_LANG` or a menu) in `odoo_instance_manager.py`.
- [x] 2.1 Add the `ui-localization` spec.
- [x] 2.2 Add `tests/test_i18n.py`.
- [x] 2.3 Add `docs/language.md`, linked from the README.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a VM: start with English and confirm menus/prompts/titles are English and behavior is unchanged.
