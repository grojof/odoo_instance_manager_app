"""The neutralisation catalogue: guarded, complete for what a copy must not do."""

from __future__ import annotations

import unittest

from instance_manager import neutralise

URL = "http://127.0.0.1:8069"


class CatalogueTests(unittest.TestCase):
    def test_rule_ids_are_unique(self) -> None:
        ids = [rule.id for rule in neutralise.CATALOGUE]
        self.assertEqual(len(ids), len(set(ids)))

    def test_what_a_copy_must_not_do_is_covered(self) -> None:
        ids = {rule.id for rule in neutralise.CATALOGUE}
        for needed in ("crons", "mail-servers", "fetchmail", "mail-template-server", "payment-provider",
                       "payment-acquirer-state", "payment-acquirer-environment", "sii-oca", "sii-odoo",
                       "edi-proxy", "webhooks", "iap", "oauth", "base-url", "queued-jobs"):
            self.assertIn(needed, ids)

    def test_every_rule_names_its_source(self) -> None:
        for rule in neutralise.CATALOGUE:
            self.assertTrue(rule.source, rule.id)


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = neutralise.apply_sql(URL)

    def test_one_statement_guarded_per_rule(self) -> None:
        self.assertTrue(self.sql.startswith("DO $$") and self.sql.endswith("END $$;"))
        self.assertEqual(self.sql.count("FROM pg_attribute a JOIN pg_class c"), len(neutralise.CATALOGUE) + 1)

    def test_housekeeping_cron_stays(self) -> None:
        self.assertIn("('base', 'autovacuum_job')", self.sql)

    def test_mail_credentials_are_dropped_and_a_sink_added(self) -> None:
        self.assertIn("smtp_pass = NULL", self.sql)
        self.assertIn(f"'{neutralise.MAIL_SINK_NAME}'", self.sql)
        self.assertIn("'invalid'", self.sql)

    def test_base_url_is_local(self) -> None:
        self.assertIn(f"value = '{URL}'", self.sql)

    def test_size_fits_one_shell_word(self) -> None:
        # Passed as one argument to `bash -c`: Linux caps one argument at 128 KiB.
        self.assertLess(len(self.sql), 100_000)


class GuardTests(unittest.TestCase):
    def test_guard_raises_and_writes_nothing(self) -> None:
        sql = neutralise.guard_sql(URL)
        self.assertIn("RAISE EXCEPTION", sql)
        self.assertNotIn("UPDATE ", sql)
        self.assertNotIn("INSERT ", sql)
        self.assertIn("mail-sink (missing)", sql)

    def test_check_sql_only_selects(self) -> None:
        sql = neutralise.check_sql(list(neutralise.CATALOGUE), URL)
        self.assertNotIn("UPDATE ", sql)
        self.assertEqual(sql.count("SELECT 'crons'"), 1)

    def test_applicable_needs_every_column(self) -> None:
        existing = {("ir_cron", "id"), ("ir_cron", "active")}
        self.assertEqual(neutralise.applicable(existing), [])
        existing.add(("ir_cron", "cron_name"))
        self.assertEqual([r.id for r in neutralise.applicable(existing)], ["crons"])


if __name__ == "__main__":
    unittest.main()
