"""Tests for interactive prompt helpers that don't require a real TTY."""

from __future__ import annotations

import builtins
import contextlib
import io
import unittest
from collections.abc import Iterator

from instance_manager import prompts


@contextlib.contextmanager
def scripted_input(answers: list[str]) -> Iterator[None]:
    """Feed ``answers`` to successive ``input()`` calls; silence stdout."""
    it: Iterator[str] = iter(answers)
    original = builtins.input
    builtins.input = lambda *_args, **_kwargs: next(it)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        builtins.input = original


class AskBoolTests(unittest.TestCase):
    def test_accepts_accented_si(self) -> None:
        with scripted_input(["sí"]):
            self.assertTrue(prompts.ask_bool("¿Continuar?", default=False))

    def test_accepts_common_affirmatives_and_negatives(self) -> None:
        for token, expected in [("s", True), ("y", True), ("no", False), ("n", False)]:
            with self.subTest(token=token), scripted_input([token]):
                self.assertEqual(prompts.ask_bool("¿Continuar?", default=not expected), expected)

    def test_empty_returns_default(self) -> None:
        with scripted_input([""]):
            self.assertTrue(prompts.ask_bool("¿Continuar?", default=True))
        with scripted_input([""]):
            self.assertFalse(prompts.ask_bool("¿Continuar?", default=False))

    def test_reprompts_on_unrecognized_then_accepts(self) -> None:
        with scripted_input(["maybe", "sí"]):
            self.assertTrue(prompts.ask_bool("¿Continuar?", default=False))


if __name__ == "__main__":
    unittest.main()
