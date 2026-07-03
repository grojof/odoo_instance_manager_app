# Tasks

- [x] 1.1 `render_table`: compute natural widths, fit to terminal width (`_fit_caps`), and wrap long plain
  cells (`_wrap_cell`) while keeping ANSI tags intact; add an optional `max_width` parameter.
- [x] 1.2 Render headers and rows uniformly as multiline cells (tight rectangle).
- [x] 2.1 Add `tests/test_ui.py` (wrap-within-width, rectangular output, ANSI preserved, empty headers).
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a narrow terminal, confirm status/report tables with long values stay aligned and
  readable.
