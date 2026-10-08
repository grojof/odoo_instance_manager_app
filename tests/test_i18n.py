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


# --- every operator-facing string has a Spanish entry ------------------------
# The same check odoo_dwg runs (its tests/test_i18n.py): an AST scan of the calls
# whose argument the UI translates at a chokepoint.

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from instance_manager import i18n  # noqa: E402

PACKAGE = Path(__file__).resolve().parent.parent / "instance_manager"
_FIRST_ARG = {"t", "tf", "ask_text", "ask_bool", "ask_int", "ask_secret", "prompt_label", "title",
              "confirm_with_phrase", "choose", "Command", "select_file_path"}


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _ui_literals() -> dict[str, str]:
    """Every string literal the UI translates, mapped to where it appears."""
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            candidates: list[ast.expr] = []
            if name in _FIRST_ARG and node.args:
                candidates.append(node.args[0])
            if name == "select_file_path" and len(node.args) > 1:
                candidates.append(node.args[1])
            if name == "level_text" and len(node.args) > 1:
                candidates.append(node.args[1])
            if name in ("choose", "render_table"):
                listed = node.args[1] if name == "choose" and len(node.args) > 1 else (
                    node.args[0] if name == "render_table" and node.args else None
                )
                if isinstance(listed, ast.BinOp):
                    listed = listed.left
                if isinstance(listed, ast.List):
                    candidates += listed.elts
            for candidate in candidates:
                if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                    if candidate.value.strip() and any(ch.isalpha() for ch in candidate.value):
                        found.setdefault(candidate.value, f"{path.name}:{candidate.lineno}")
    return found


class CatalogTests(unittest.TestCase):
    def test_every_ui_string_has_a_spanish_translation(self) -> None:
        literals = _ui_literals()
        self.assertGreater(len(literals), 300)  # the extractor still sees the UI
        missing = {text: where for text, where in literals.items() if text not in i18n._ES}
        self.assertFalse(missing, f"add these to i18n._ES: {missing}")

    def test_the_catalog_is_authored_in_the_direction_it_is_read(self) -> None:
        """English keys, Spanish values — the direction t() looks up."""
        self.assertGreater(len(i18n._ES), 500)
        spanish_only = {"á", "é", "í", "ó", "ú", "¿", "¡", "ñ"}
        suspicious = [k for k in i18n._ES if k != "Español" and any(ch in k for ch in spanish_only)]
        self.assertFalse(suspicious, f"these keys look Spanish: {suspicious}")
