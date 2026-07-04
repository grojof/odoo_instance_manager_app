"""Tests for system execution helpers (stdlib subprocess, no third-party deps)."""

from __future__ import annotations

import contextlib
import io
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

        def fake_run(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, "db1\n", "")

        with mock.patch.object(system, "run", fake_run):
            system.list_databases("127.0.0.1", 5432, "shop", "pw", **kwargs)  # type: ignore[arg-type]
        return captured["cmd"]

    def test_owner_scopes_by_role_and_prefix(self) -> None:
        cmd = self._captured_query(owner="shop")
        self.assertIn("r.rolname = 'shop'", cmd)
        self.assertIn("d.datname LIKE 'shop%'", cmd)

    def test_no_owner_lists_all(self) -> None:
        cmd = self._captured_query()
        self.assertIn("SELECT datname FROM pg_database WHERE datistemplate = false", cmd)
        self.assertNotIn("rolname", cmd)

    def test_unsafe_owner_falls_back_to_unfiltered(self) -> None:
        cmd = self._captured_query(owner="a';DROP DATABASE x;--")
        self.assertNotIn("rolname", cmd)


if __name__ == "__main__":
    unittest.main()
