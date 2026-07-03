# Fix plan-preview wrapping for long/multi-line commands

## Why

The table-fitting fix still broke on the **plan preview**. `preview_commands` rendered each command inside a
table column *and* styled the whole command with `style(..., "dim")`. Because the cell was fully ANSI-wrapped,
the table's line-wrapper skipped it (to avoid splitting escape sequences), so long or multi-line commands —
notably the heredoc that writes `odoo.conf` (embedded newlines + long `addons_path`) — overflowed the terminal
and the preview "fell apart".

## What changes

- **Plan preview is now a list, not a table.** Each command is printed below its numbered description,
  indented and wrapped to the terminal width. Multi-line commands (heredocs) keep their line breaks and stay
  legible; long single lines wrap instead of overflowing.
- **`render_table` wrapping is now ANSI-robust** (the general fix): long styled cells wrap on their *visible*
  text, re-applying a leading `style()` prefix and trailing reset to each wrapped piece, so escapes are never
  split and short styled tags are unchanged.
- New `ui.wrap_plain_block(text, width)` helper (wrap each line of a multi-line string) backs both the preview
  and the table wrapper.

## Impact

- Affected code: `instance_manager/system.py` (`preview_commands` → list), `instance_manager/ui.py`
  (`wrap_plain_block`, ANSI-aware `_wrap_cell`).
- Presentation only — no capability behavior changes, no spec delta (the preview still shows every command
  with its index and description, per `execution-safety`).
- New `ui` tests; stdlib only.
