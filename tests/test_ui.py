"""Tests for terminal table rendering, especially long-text wrapping."""

from __future__ import annotations

import unittest

from instance_manager.ui import _visible_len, render_table, strip_ansi


class RenderTableTests(unittest.TestCase):
    def _lines(self, text: str) -> list[str]:
        return text.splitlines()

    def test_long_cell_wraps_within_max_width(self) -> None:
        long_path = "/opt/odoo/instancia/addons-custom/modulo_con_nombre_larguisimo/models/x.py " * 2
        table = render_table(["Campo", "Valor"], [["ruta", long_path.strip()]], max_width=50)
        for line in self._lines(table):
            self.assertLessEqual(_visible_len(line), 50, f"line too wide: {line!r}")
        # The content is still present (wrapped across lines).
        self.assertIn("addons-custom", strip_ansi(table))

    def test_table_is_rectangular(self) -> None:
        table = render_table(
            ["A", "B"],
            [["short", "x" * 80], ["another", "y"]],
            max_width=48,
        )
        widths = {_visible_len(line) for line in self._lines(table)}
        self.assertEqual(len(widths), 1, f"lines not aligned: {widths}")

    def test_short_table_contains_values_and_borders(self) -> None:
        table = render_table(["K", "V"], [["host", "127.0.0.1"]], max_width=80)
        plain = strip_ansi(table)
        self.assertIn("host", plain)
        self.assertIn("127.0.0.1", plain)
        self.assertTrue(plain.startswith("+"))

    def test_ansi_styled_cell_is_preserved(self) -> None:
        # A literal ANSI-wrapped tag (deterministic regardless of color support):
        # its escape sequences must survive rendering, not be split or stripped.
        tag = "\033[1m\033[32mACTIVA\033[0m"
        table = render_table(["Estado"], [[tag]], max_width=40)
        self.assertIn("\033[32m", table)
        self.assertIn("ACTIVA", strip_ansi(table))

    def test_empty_headers_returns_empty(self) -> None:
        self.assertEqual(render_table([], [], max_width=80), "")


if __name__ == "__main__":
    unittest.main()
