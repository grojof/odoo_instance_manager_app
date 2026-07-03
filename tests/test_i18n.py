"""Tests for UI translation (i18n) and its chokepoints."""

from __future__ import annotations

import builtins
import contextlib
import io
import unittest

from instance_manager import prompts
from instance_manager.i18n import current_language, set_language, t
from instance_manager.ui import render_table, strip_ansi


class TranslateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(set_language, "es")

    def test_spanish_is_identity(self) -> None:
        set_language("es")
        self.assertEqual(t("Gestionar instancias"), "Gestionar instancias")

    def test_english_translates_known_and_falls_back(self) -> None:
        set_language("en")
        self.assertEqual(t("Gestionar instancias"), "Manage instances")
        # Unknown string falls back to the source (graceful degrade).
        self.assertEqual(t("Cadena que no está en el catálogo"), "Cadena que no está en el catálogo")

    def test_set_language_normalizes(self) -> None:
        set_language("English")
        self.assertEqual(current_language(), "en")
        set_language("es-ES")
        self.assertEqual(current_language(), "es")


class ChokepointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(set_language, "es")

    def test_table_headers_translate_but_rows_do_not(self) -> None:
        set_language("en")
        table = strip_ansi(render_table(["Estado", "Detalle"], [["OK", "Servicio Odoo"]]))
        self.assertIn("State", table)
        self.assertIn("Detail", table)
        # Row data is never translated (it's data, not UI chrome).
        self.assertIn("Servicio Odoo", table)

    def test_choose_shows_translation_but_returns_original(self) -> None:
        set_language("en")
        it = iter(["1"])
        original = builtins.input
        builtins.input = lambda *_a, **_k: next(it)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                selected = prompts.choose("Menú", ["Realizar backup", "Volver"])
        finally:
            builtins.input = original
        # Display was translated…
        self.assertIn("Create backup", strip_ansi(out.getvalue()))
        # …but the returned value is the original (so caller comparisons work).
        self.assertEqual(selected, "Realizar backup")


if __name__ == "__main__":
    unittest.main()
