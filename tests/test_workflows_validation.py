"""Tests for the destructive-flow validation seam in workflows.

Ensures ``_validate_instance_or_abort`` refuses unsafe instance names before any
plan is built (guarding the shell/SQL injection surface in the delete/purge flows)
and returns a normalized, validated config for safe names.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from instance_manager.models import InstanceConfig
from instance_manager.workflows import _validate_instance_or_abort


class ValidateInstanceOrAbortTests(unittest.TestCase):
    def test_returns_none_for_unsafe_names(self) -> None:
        for name in ["x;reboot #", "x; DROP DATABASE prod; --", "Bad", "1bad", "a b"]:
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(_validate_instance_or_abort(name))

    def test_returns_validated_config_for_safe_name(self) -> None:
        config = _validate_instance_or_abort("odoo18")
        self.assertIsInstance(config, InstanceConfig)
        assert config is not None  # for type-checkers
        self.assertEqual(config.instance, "odoo18")
        # normalize_defaults ran: blank credentials filled from the instance name.
        self.assertEqual(config.db_user, "odoo18")
        # validate_identifiers ran without raising (would have returned None otherwise).


if __name__ == "__main__":
    unittest.main()
