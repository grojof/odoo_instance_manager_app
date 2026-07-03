"""Tests for operator-UX helpers: port bounds, secret prompt, and credential reuse."""

from __future__ import annotations

import builtins
import contextlib
import io
import unittest
from collections.abc import Iterator

from instance_manager import prompts
from instance_manager.workflows.common import DbCredentials, _ask_db_credentials


@contextlib.contextmanager
def scripted(inputs: list[str], secrets: list[str] | None = None) -> Iterator[None]:
    it = iter(inputs)
    sec = iter(secrets or [])
    orig_input, orig_getpass = builtins.input, prompts.getpass.getpass
    builtins.input = lambda *_a, **_k: next(it)
    prompts.getpass.getpass = lambda *_a, **_k: next(sec)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        builtins.input = orig_input
        prompts.getpass.getpass = orig_getpass


class AskPortTests(unittest.TestCase):
    def test_rejects_out_of_range_then_accepts(self) -> None:
        with scripted(["0", "70000", "8069"]):
            self.assertEqual(prompts.ask_port("HTTP", 8069), 8069)

    def test_generic_ask_int_uses_custom_bounds(self) -> None:
        with scripted(["5"]):
            self.assertEqual(prompts.ask_int("maxretry", 8, min_value=1, max_value=100), 5)


class AskSecretTests(unittest.TestCase):
    def test_reads_without_echo(self) -> None:
        with scripted([], secrets=["s3cret"]):
            self.assertEqual(prompts.ask_secret("DB password"), "s3cret")


class AskDbCredentialsTests(unittest.TestCase):
    cached = DbCredentials("db.example", 5433, "odoo", "pw")

    def test_reuses_cached_on_yes(self) -> None:
        # ask_bool reads one input ("s" = yes) -> returns the cached creds unchanged.
        with scripted(["s"]):
            result = _ask_db_credentials("odoo", self.cached)
        self.assertIs(result, self.cached)

    def test_collects_fresh_when_no_cache(self) -> None:
        # No cache -> no reuse prompt: host, port, user via input; password via getpass.
        with scripted(["127.0.0.1", "5432", "odoo18"], secrets=["fresh"]):
            result = _ask_db_credentials("odoo18")
        self.assertEqual(result, DbCredentials("127.0.0.1", 5432, "odoo18", "fresh"))

    def test_collects_fresh_when_cache_declined(self) -> None:
        # Cache present but declined ("n"), then fresh values collected.
        with scripted(["n", "10.0.0.9", "5432", "acme"], secrets=["pw2"]):
            result = _ask_db_credentials("acme", self.cached)
        self.assertEqual(result, DbCredentials("10.0.0.9", 5432, "acme", "pw2"))


if __name__ == "__main__":
    unittest.main()
