"""Tests for system execution helpers (stdlib subprocess, no third-party deps)."""

from __future__ import annotations

import contextlib
import io
import subprocess
import unittest

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


if __name__ == "__main__":
    unittest.main()
