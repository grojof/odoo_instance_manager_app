from __future__ import annotations

import os
import re
import sys

_RESET = "\033[0m"
_STYLES = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}


def supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True

    stream = sys.stdout
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False

    term = os.environ.get("TERM", "").lower()
    if term in {"", "dumb"}:
        return False

    return True


def style(text: str, *tokens: str) -> str:
    if not supports_color() or not tokens:
        return text

    prefix = "".join(_STYLES[token] for token in tokens if token in _STYLES)
    if not prefix:
        return text
    return f"{prefix}{text}{_RESET}"


def level_text(level: str, message: str) -> str:
    token_map = {
        "INFO": ("blue",),
        "WARN": ("yellow", "bold"),
        "ERROR": ("red", "bold"),
        "OK": ("green", "bold"),
        "MISSING": ("yellow", "bold"),
    }
    tokens = token_map.get(level, ())
    label = style(f"[{level}]", *tokens)
    return f"{label} {message}" if label else f"[{level}] {message}"


def level_tag(level: str) -> str:
    return level_text(level, "").rstrip()


def prompt_label(label: str) -> str:
    return style(label, "cyan")


def title(text: str) -> str:
    return style(text, "bold")


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    safe_headers = [str(item) for item in headers]
    safe_rows = [[str(cell) for cell in row] for row in rows]
    column_count = len(safe_headers)
    if column_count == 0:
        return ""

    normalized_rows = []
    for row in safe_rows:
        if len(row) < column_count:
            normalized_rows.append(row + [""] * (column_count - len(row)))
        else:
            normalized_rows.append(row[:column_count])

    widths = [_visible_len(head) for head in safe_headers]
    for row in normalized_rows:
        for index, cell in enumerate(row):
            cell_lines = cell.splitlines() or [""]
            for line in cell_lines:
                widths[index] = max(widths[index], _visible_len(line))

    def _pad(cell: str, width: int) -> str:
        extra = width - _visible_len(cell)
        return cell + (" " * max(0, extra))

    horizontal = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    header_line = "| " + " | ".join(_pad(head, widths[idx]) for idx, head in enumerate(safe_headers)) + " |"

    lines = [horizontal, header_line, horizontal]
    for row in normalized_rows:
        split_cells = [cell.splitlines() or [""] for cell in row]
        row_height = max(len(parts) for parts in split_cells)
        for line_idx in range(row_height):
            rendered_cells: list[str] = []
            for col_idx, parts in enumerate(split_cells):
                chunk = parts[line_idx] if line_idx < len(parts) else ""
                rendered_cells.append(_pad(chunk, widths[col_idx]))
            body_line = "| " + " | ".join(rendered_cells) + " |"
            lines.append(body_line)
    lines.append(horizontal)
    return "\n".join(lines)
