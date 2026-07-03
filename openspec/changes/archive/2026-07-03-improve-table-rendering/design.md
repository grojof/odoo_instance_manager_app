# Design

## Fit-then-wrap

1. **Natural widths** — the longest visible line per column (ANSI-aware via `_visible_len`).
2. **Available width** — `max_width` (default `shutil.get_terminal_size((100, 24)).columns`) minus the border
   overhead (`3 * columns + 1` for `"| "`, `" | "` separators, and `" |"`).
3. **Fit** — `_fit_caps` shrinks the widest column by one until `sum(caps) <= available`, with a `_MIN_COL`
   (10) floor so columns never collapse to nothing.
4. **Wrap** — `_wrap_cell` wraps each plain line to its column cap with `textwrap.wrap(break_long_words=True,
   break_on_hyphens=False)` so long paths/commands break cleanly. Lines containing ANSI escapes are left
   intact (they are short status tags; wrapping them could split an escape sequence).
5. **Render** — headers and rows are rendered by the same multiline routine; actual column widths are taken
   from the wrapped content (≤ caps), so the table is a tight rectangle.

## Why not detect a "long" column and truncate

Truncating (`…`) hides data an operator may need (a full path, a cert subject). Wrapping keeps everything
visible and readable. The `_MIN_COL` floor plus water-filling keeps the widest column from starving the
others.

## ANSI safety

Wrapping counts *visible* length (`_visible_len` strips ANSI) but only wraps lines with no escape sequences,
so styled cells (e.g. an `ACTIVA`/`INACTIVA` tag) are never split mid-escape. This matches how the codebase
uses styling: long content is plain, styling is on short tags.

## Testing

`tests/test_ui.py` pins `max_width` for determinism: a long path wraps so no line exceeds the width, the table
stays rectangular (all lines equal visible width), short tables keep their values/borders, a literal
ANSI-wrapped tag survives, and empty headers return `""`.
