# Tasks

- [x] 1.1 Add `ui.wrap_plain_block(text, width)`.
- [x] 1.2 Make `_wrap_cell` ANSI-robust (wrap visible text; re-apply leading SGR + trailing reset).
- [x] 2.1 Rewrite `preview_commands` as an indented, width-wrapped list (no table); drop the now-unused
  `render_table` import there.
- [x] 3.1 Add `ui` tests (`wrap_plain_block`; long dim-styled cell wraps + keeps ANSI).
- [x] 4.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 4.2 (operator) On a narrow terminal, confirm the plan preview for an install (with the `odoo.conf`
  heredoc) wraps and stays readable.
