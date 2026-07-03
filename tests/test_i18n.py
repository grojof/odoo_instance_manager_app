"""Tests for UI translation (i18n) and its chokepoints.

English is the source language (the string in the code is the key). With English
selected, ``t`` is the identity; with Spanish selected it looks up the catalog.
"""

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
        self.addCleanup(set_language, "en")

    def test_english_is_identity(self) -> None:
        set_language("en")
        self.assertEqual(t("Manage instances"), "Manage instances")

    def test_spanish_translates_known_and_falls_back(self) -> None:
        set_language("es")
        self.assertEqual(t("Manage instances"), "Gestionar instancias")
        # Unknown string falls back to the source (graceful degrade).
        self.assertEqual(t("A string not in the catalog"), "A string not in the catalog")

    def test_set_language_normalizes(self) -> None:
        set_language("English")
        self.assertEqual(current_language(), "en")
        set_language("es-ES")
        self.assertEqual(current_language(), "es")


class ChokepointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(set_language, "en")

    def test_table_headers_and_string_cells_translate(self) -> None:
        set_language("es")
        table = strip_ansi(render_table(["State", "Detail"], [["OK", "Odoo service"]]))
        self.assertIn("Estado", table)
        self.assertIn("Detalle", table)
        # String cells present in the catalog are translated too.
        self.assertIn("Servicio Odoo", table)

    def test_choose_shows_translation_but_returns_original(self) -> None:
        set_language("es")
        it = iter(["1"])
        original = builtins.input
        builtins.input = lambda *_a, **_k: next(it)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                selected = prompts.choose("Menu", ["Create backup", "Back"])
        finally:
            builtins.input = original
        # Display was translated…
        self.assertIn("Realizar backup", strip_ansi(out.getvalue()))
        # …but the returned value is the original English (so caller comparisons work).
        self.assertEqual(selected, "Create backup")


if __name__ == "__main__":
    unittest.main()
