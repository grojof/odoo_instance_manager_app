"""Tests for InstanceConfig identifier validation and default normalization.

Written with stdlib unittest so they run today via ``python -m unittest`` with no
third-party dependency; they are also collected by pytest once it is added.
"""

from __future__ import annotations

import unittest

from instance_manager.models import InstanceConfig


class ValidateIdentifiersTests(unittest.TestCase):
    def test_rejects_unsafe_instance_names(self) -> None:
        unsafe = [
            "1bad",          # must start with a letter
            "Bad",           # uppercase not allowed
            "a" * 33,        # exceeds 32 chars
            "con-guion",     # hyphen not allowed
            "x;reboot",      # shell metacharacters
            "x; DROP DATABASE prod; --",  # SQL injection payload
            "my odoo",       # space
            "",              # empty
        ]
        for name in unsafe:
            with self.subTest(name=name):
                config = InstanceConfig(instance=name)
                config.normalize_defaults()
                with self.assertRaises(ValueError):
                    config.validate_identifiers()

    def test_accepts_safe_instance_names(self) -> None:
        safe = ["odoo18", "a", "a_b", "prod_2024", "x" * 32]
        for name in safe:
            with self.subTest(name=name):
                config = InstanceConfig(instance=name)
                config.normalize_defaults()
                config.validate_identifiers()  # must not raise

    def test_rejects_unsafe_db_user(self) -> None:
        config = InstanceConfig(instance="odoo18")
        config.db_user = "bad-user"  # hyphen invalid for a PostgreSQL identifier
        with self.assertRaises(ValueError):
            config.validate_identifiers()


class NormalizeDefaultsTests(unittest.TestCase):
    def test_blank_db_user_defaults_to_instance_name_but_secrets_do_not(self) -> None:
        # The DB user (an identifier) may default to the instance name; secrets
        # must never fall back to the guessable instance name.
        config = InstanceConfig(instance="acme")
        config.normalize_defaults()
        self.assertEqual(config.db_user, "acme")
        self.assertEqual(config.db_password, "")
        self.assertEqual(config.odoo_admin_passwd, "")

    def test_existing_credentials_are_preserved(self) -> None:
        config = InstanceConfig(instance="acme")
        config.db_user = "acme_ro"
        config.db_password = "secret"
        config.normalize_defaults()
        self.assertEqual(config.db_user, "acme_ro")
        self.assertEqual(config.db_password, "secret")


class EnsureStrongSecretsTests(unittest.TestCase):
    def test_blank_secrets_get_strong_non_instance_values(self) -> None:
        config = InstanceConfig(instance="acme")
        config.normalize_defaults()
        config.ensure_strong_secrets()
        self.assertNotEqual(config.db_password, "")
        self.assertNotEqual(config.db_password, "acme")
        self.assertNotEqual(config.odoo_admin_passwd, "acme")
        self.assertGreaterEqual(len(config.db_password), 20)
        self.assertFalse(config.uses_instance_name_secret())

    def test_existing_secrets_are_not_overwritten(self) -> None:
        config = InstanceConfig(instance="acme")
        config.db_password = "chosen"
        config.odoo_admin_passwd = "master"
        config.ensure_strong_secrets()
        self.assertEqual(config.db_password, "chosen")
        self.assertEqual(config.odoo_admin_passwd, "master")


if __name__ == "__main__":
    unittest.main()
