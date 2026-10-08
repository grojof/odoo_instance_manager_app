"""Tests for InstanceConfig identifier validation and default normalization.

Written with stdlib unittest so they run today via ``python -m unittest`` with no
third-party dependency; they are also collected by pytest once it is added.
"""

from __future__ import annotations

import unittest

from instance_manager.models import (
    InstanceConfig,
    branch_error,
    db_host_error,
    domain_error,
    host_cidr,
    ip_error,
    is_valid_db_name,
    version_error,
)


class OperatorValueTests(unittest.TestCase):
    """Values that reach a root shell, nginx or odoo.conf are refused unless plain."""

    HOSTILE = ["x'$(id)'", "a b", "a;b", "a`id`", "$(id)", "a\nb", ""]

    def test_domain(self) -> None:
        for good in ("odooprodserver.local", "erp.example.com", "*.example.com", "localhost"):
            self.assertIsNone(domain_error(good), good)
        for bad in [*self.HOSTILE, "-x.com", "a..b", "*.*.com", "x.com;"]:
            self.assertIsNotNone(domain_error(bad), bad)

    def test_branch_and_version(self) -> None:
        for good in ("18.0", "17.0", "saas-17.4", "feature/x"):
            self.assertIsNone(branch_error(good), good)
        for bad in [*self.HOSTILE, "-b", "a..b", "x.lock", "18.0/"]:
            self.assertIsNotNone(branch_error(bad), bad)
        for good in ("18", "18.0", "9"):
            self.assertIsNone(version_error(good), good)
        for bad in [*self.HOSTILE, "18.1", "v18", "100"]:
            self.assertIsNotNone(version_error(bad), bad)

    def test_ip_and_db_host(self) -> None:
        self.assertIsNone(ip_error("10.0.0.5"))
        self.assertIsNone(ip_error("2001:db8::1"))
        for bad in self.HOSTILE:
            self.assertIsNotNone(ip_error(bad), bad)
        self.assertEqual(host_cidr("10.0.0.5"), "10.0.0.5/32")
        self.assertEqual(host_cidr("2001:db8::1"), "2001:db8::1/128")
        for good in ("", "127.0.0.1", "db.example.com", "/var/run/postgresql", "False"):
            self.assertIsNone(db_host_error(good), good)
        for bad in [h for h in self.HOSTILE if h]:
            self.assertIsNotNone(db_host_error(bad), bad)

    def test_db_name_is_odoos_pattern(self) -> None:
        self.assertTrue(is_valid_db_name("prod-2024.copy_1"))
        for bad in ["-x", "_x", "a", "a b", "a'b", "x" * 64]:
            self.assertFalse(is_valid_db_name(bad), bad)

    def test_validate_identifiers_refuses_a_hostile_branch(self) -> None:
        config = InstanceConfig(instance="shop", repo_branch="18.0' $(id) '")
        config.normalize_defaults()
        with self.assertRaises(ValueError):
            config.validate_identifiers()


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
