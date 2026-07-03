# Improve table rendering for long text

## Why

`render_table` sized each column to its longest cell with no upper bound. A single long value — an
`addons_path`, a certificate subject, a command, a filestore list — made its column wider than the terminal,
so the terminal hard-wrapped the line and the table "fell apart" (misaligned borders, unreadable rows).

## What changes

`render_table` now **fits the terminal width and wraps long cells** instead of overflowing:

- Compute each column's natural width, then, if the row would exceed the available width
  (`shutil.get_terminal_size()` minus borders), shrink the widest column(s) until it fits.
- Wrap plain cell text to the resulting per-column cap (`textwrap`, breaking long tokens like paths). Styled
  (ANSI) tags are short and are left intact so escape sequences are never split.
- Render headers and rows uniformly as multiline cells, keeping the table a clean rectangle.
- An optional `max_width` parameter makes the behavior deterministic for tests.

This is presentation only — no capability behavior changes, so there is no spec delta.

## Impact

- Affected code: `instance_manager/ui.py` (`render_table` + `_fit_caps` / `_wrap_cell` helpers).
- New `tests/test_ui.py` (wrapping within width, rectangular output, ANSI preserved).
- stdlib only (`shutil`, `textwrap`); `dependencies = []` unchanged.
