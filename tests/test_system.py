"""Tests for system execution helpers (stdlib subprocess, no third-party deps)."""

from __future__ import annotations

import contextlib
import io
import shlex
import subprocess
import unittest
from unittest import mock

from instance_manager import system
from instance_manager.system import run_streaming


def _bash_lc_works() -> bool:
    """True only if `bash -lc` actually runs (skips hosts where it routes to a
    broken shim, e.g. Git-for-Windows' WSL relay). CI on Ubuntu returns True."""
    try:
        return subprocess.run(["bash", "-lc", "exit 0"]).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_bash_lc_works(), "a working `bash -lc` is required")
class RunStreamingTests(unittest.TestCase):
    def test_captures_output_and_zero_returncode(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = run_streaming("printf 'line1\\nline2\\n'")
        self.assertEqual(result.returncode, 0)
        self.assertIn("line1", result.stdout)
        self.assertIn("line2", result.stdout)
        # Output was also streamed live to stdout.
        self.assertIn("line1", out.getvalue())

    def test_merges_stderr_into_stdout(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_streaming("echo err 1>&2")
        self.assertEqual(result.returncode, 0)
        self.assertIn("err", result.stdout)

    def test_propagates_nonzero_returncode(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_streaming("exit 3")
        self.assertEqual(result.returncode, 3)

    def test_stdin_is_closed_so_reads_do_not_block(self) -> None:
        # `cat` with no args would hang on an open stdin; DEVNULL makes it EOF at once.
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_streaming("cat")
        self.assertEqual(result.returncode, 0)


class ListDatabasesOwnerScopeTests(unittest.TestCase):
    def _captured_query(self, **kwargs: object) -> str:
        captured: dict[str, str] = {}

        def fake_run(cmd: str, check: bool = False, env=None) -> subprocess.CompletedProcess:
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, "db1\n", "")

        with mock.patch.object(system, "run", fake_run):
            system.list_databases("127.0.0.1", 5432, "shop", "pw", **kwargs)  # type: ignore[arg-type]
        return captured["cmd"]

    def test_owner_scopes_by_role_and_exact_name(self) -> None:
        cmd = shlex.split(self._captured_query(owner="shop"))[-1]
        self.assertIn("r.rolname = 'shop'", cmd)
        self.assertIn("d.datname = 'shop'", cmd)
        # No name prefix: instance `shop` must not list `shop2` or `shop_eu`.
        self.assertNotIn("LIKE", cmd)

    def test_no_owner_lists_all(self) -> None:
        cmd = self._captured_query()
        self.assertIn("SELECT datname FROM pg_database WHERE datistemplate = false", cmd)
        self.assertNotIn("rolname", cmd)

    def test_unsafe_owner_falls_back_to_unfiltered(self) -> None:
        cmd = self._captured_query(owner="a';DROP DATABASE x;--")
        self.assertNotIn("rolname", cmd)


class ProbeQuotingTests(unittest.TestCase):
    """Probes run before any preview, so they quote what they are given."""

    def _captured(self, probe, value: str) -> str:
        captured: dict[str, str] = {}

        def fake_run(cmd: str, check: bool = False, env=None) -> subprocess.CompletedProcess:
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 1, "", "")

        with mock.patch.object(system, "run", fake_run):
            probe(value)
        return captured["cmd"]

    def test_shell_probes_quote_their_argument(self) -> None:
        hostile = "x'; touch /tmp/pwned; '"
        for probe in (system.path_exists, system.user_exists, system.service_exists):
            with self.subTest(probe=probe.__name__):
                cmd = self._captured(probe, hostile)
                self.assertIn(shlex.quote(hostile), cmd)

    def test_sql_probes_escape_their_argument(self) -> None:
        for probe in (system.database_exists, system.db_role_exists, system.database_owner):
            with self.subTest(probe=probe.__name__):
                cmd = self._captured(probe, "o'brien$(id)")
                sql = shlex.split(cmd)[-1]  # the -c argument, as psql receives it
                self.assertIn("= 'o''brien$(id)'", sql)


if __name__ == "__main__":
    unittest.main()
