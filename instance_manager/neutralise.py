"""Neutralising a copy of a production database.

A copy of production is armed the moment an Odoo starts on it: every cron is
overdue, mail goes out through production's servers (or, with none active,
through the ``smtp_server`` fallback of ``odoo.conf``), a payment provider or a
tax integration in production mode is one click from a real transaction, and
the copy calls webhooks, calendars and IAP services as production.

Odoo's own ``neutralize`` exists only from 16.0 and knows nothing of OCA
modules. These rules follow it (``data/neutralize.sql`` of each module, cited
per rule) and cover 12.0-19.0 and the OCA modules a Spanish or queue-based
instance runs: each rule is guarded by the existence of the table and every
column it touches, so one catalogue serves every version. It is one-way, like
Odoo's: a copy is not given back to production, and recording the values it
replaces would keep production's mail passwords inside the copy.

The catalogue is the one the sibling project odoo_dwg keeps
(``odoo_dwg/neutralise.py``), there made reversible. Pure: this module builds
SQL; running it is ``system``'s job.
"""

from __future__ import annotations

from dataclasses import dataclass

_ODOO = "odoo {} {}/data/neutralize.sql"

#: The outgoing server every neutralised database sends through: a host that does
#: not resolve, so nothing leaves, and Odoo never falls back to odoo.conf's server.
MAIL_SINK_NAME = "neutralised: no mail leaves this copy"
MAIL_SINK_HOST = "invalid"
MAIL_SINK_PORT = 1025


@dataclass(frozen=True)
class Keep:
    """A cron left active: housekeeping that sends nothing."""

    xmlid: str
    reason: str


#: Matched by external identifier, never by name (names are translated and edited).
HOUSEKEEPING = (
    Keep("base.autovacuum_job",
         "Odoo's own neutralisation keeps exactly this cron (odoo 16.0-19.0 "
         "odoo/addons/base/data/neutralize.sql); it vacuums internal data and calls nothing."),
    Keep("queue_job.ir_cron_autovacuum_queue_jobs",
         "Deletes old done jobs (OCA/queue queue_job/data/queue_data.xml); runs no job."),
)


@dataclass(frozen=True)
class Rule:
    """Set ``sets`` on the rows of ``table`` (alias ``t``) matching ``where``.

    A rule applies only where its table and every column it names exist."""

    id: str
    source: str
    table: str
    where: str
    sets: tuple[tuple[str, str], ...]
    requires: tuple[str, ...] = ()
    label: str = ""

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(("id", *self.requires, *(c for c, _ in self.sets),
                                    *((self.label,) if self.label else ()))))


def _keep_ids() -> str:
    pairs = ", ".join(f"('{k.xmlid.split('.')[0]}', '{k.xmlid.split('.')[1]}')" for k in HOUSEKEEPING)
    return (f"t.id NOT IN (SELECT res_id FROM ir_model_data WHERE model = 'ir.cron' "
            f"AND (module, name) IN ({pairs}))")


def _param(key: str) -> str:
    return f"t.key = '{key}'"


CATALOGUE: tuple[Rule, ...] = (
    Rule("crons", _ODOO.format("16.0-19.0", "odoo/addons/base"),
         "ir_cron", f"t.active AND {_keep_ids()}", (("active", "false"),), label="cron_name"),
    Rule("mail-servers", _ODOO.format("16.0-19.0", "odoo/addons/base")
         + " (deactivated, credentials dropped)",
         "ir_mail_server", f"t.name <> '{MAIL_SINK_NAME}' AND (t.active OR t.smtp_user IS NOT NULL "
         "OR t.smtp_pass IS NOT NULL)",
         (("active", "false"), ("smtp_user", "NULL"), ("smtp_pass", "NULL")), label="name"),
    Rule("fetchmail", "odoo 12.0-19.0 addons/fetchmail (mail/models/fetchmail.py from 17.0)",
         "fetchmail_server", "t.active", (("active", "false"),), label="name"),
    Rule("mail-template-server", _ODOO.format("16.0-19.0", "addons/mail"),
         "mail_template", "t.mail_server_id IS NOT NULL", (("mail_server_id", "NULL"),)),
    Rule("queued-jobs", "OCA/queue queue_job/job.py (pending, enqueued and started are what "
         "the job runner executes; held as failed, which it never picks up)",
         "queue_job", "t.state IN ('pending', 'enqueued', 'started', 'wait_dependencies')",
         (("state", "'failed'"),), label="name"),
    Rule("sii-oca", "OCA/l10n-spain l10n_es_aeat_sii(_oca)/models/res_company.py",
         "res_company", "t.sii_enabled OR NOT coalesce(t.sii_test, false)",
         (("sii_enabled", "false"), ("sii_test", "true")), label="name"),
    Rule("sii-odoo", _ODOO.format("16.0-19.0", "addons/l10n_es_edi_sii"),
         "res_company", "NOT coalesce(t.l10n_es_sii_test_env, false)",
         (("l10n_es_sii_test_env", "true"),), label="name"),
    Rule("ticketbai", _ODOO.format("17.0-19.0", "addons/l10n_es_edi_tbai"),
         "res_company", "NOT coalesce(t.l10n_es_tbai_test_env, false)",
         (("l10n_es_tbai_test_env", "true"),), label="name"),
    Rule("edi-proxy", _ODOO.format("16.0-19.0", "addons/account_edi_proxy_client"),
         "account_edi_proxy_client_user",
         "t.edi_mode = 'prod' AND t.proxy_type NOT IN ('l10n_my_edi', 'l10n_gr_edi')",
         (("edi_mode", "CASE WHEN t.proxy_type IN ('l10n_it_edi', 'peppol', 'nemhandel', "
                       "'pdp') THEN 'demo' ELSE 'test' END"),), requires=("proxy_type",)),
    Rule("peppol-mode", _ODOO.format("17.0-19.0", "addons/account_peppol"),
         "ir_config_parameter", f"{_param('account_peppol.edi.mode')} AND t.value <> 'demo'",
         (("value", "'demo'"),), requires=("key",), label="key"),
    Rule("payment-provider", _ODOO.format("16.0-19.0", "addons/payment"),
         "payment_provider", "t.state NOT IN ('test', 'disabled')", (("state", "'disabled'"),),
         label="code"),
    Rule("payment-acquirer-state", "odoo 13.0-15.0 addons/payment/models/payment_acquirer.py",
         "payment_acquirer", "t.state NOT IN ('test', 'disabled')", (("state", "'disabled'"),),
         label="provider"),
    Rule("payment-acquirer-environment", "odoo 12.0 addons/payment/models/payment_acquirer.py",
         "payment_acquirer", "t.environment = 'prod'", (("environment", "'test'"),),
         label="provider"),
    Rule("delivery-environment", _ODOO.format("16.0-19.0", "addons/delivery"),
         "delivery_carrier", "t.prod_environment", (("prod_environment", "false"),)),
    Rule("delivery-external", _ODOO.format("16.0-19.0", "addons/delivery"),
         "delivery_carrier", "t.active AND t.delivery_type NOT IN ('fixed', 'base_on_rule')",
         (("active", "false"),), requires=("delivery_type",)),
    Rule("oauth", _ODOO.format("16.0-19.0", "addons/auth_oauth"),
         "auth_oauth_provider", "t.enabled", (("enabled", "false"),)),
    Rule("google-calendar-users", "odoo 12.0-15.0 addons/google_calendar/models/res_users.py",
         "res_users", "t.google_calendar_rtoken IS NOT NULL OR t.google_calendar_token IS NOT NULL",
         (("google_calendar_rtoken", "NULL"), ("google_calendar_token", "NULL"))),
    Rule("google-calendar-settings", _ODOO.format("16.0-19.0", "addons/google_calendar"),
         "res_users_settings",
         "t.google_calendar_rtoken IS NOT NULL OR t.google_calendar_token IS NOT NULL",
         (("google_calendar_rtoken", "NULL"), ("google_calendar_token", "NULL"),
          ("google_synchronization_stopped", "true"))),
    Rule("microsoft-calendar-users", _ODOO.format("16.0-19.0", "addons/microsoft_calendar"),
         "res_users",
         "t.microsoft_calendar_token IS NOT NULL OR t.microsoft_calendar_rtoken IS NOT NULL",
         (("microsoft_calendar_token", "NULL"), ("microsoft_calendar_rtoken", "NULL"))),
    Rule("microsoft-calendar-settings", _ODOO.format("16.0-19.0", "addons/microsoft_calendar"),
         "res_users_settings", "t.microsoft_calendar_sync_token IS NOT NULL",
         (("microsoft_calendar_sync_token", "NULL"), ("microsoft_synchronization_stopped", "true"))),
    Rule("webhooks", _ODOO.format("17.0-19.0", "odoo/addons/base"),
         "ir_act_server",
         "t.state = 'webhook' AND t.webhook_url IS DISTINCT FROM 'neutralised: webhook disabled'",
         (("webhook_url", "'neutralised: webhook disabled'"),), requires=("state",), label="name"),
    Rule("iap", _ODOO.format("16.0-19.0", "addons/iap"),
         "iap_account", "t.account_token NOT LIKE '%+disabled'",
         (("account_token", "regexp_replace(t.account_token, '(\\+.*)?$', '+disabled')"),),
         label="service_name"),
    Rule("website-domain", _ODOO.format("16.0-19.0", "addons/website"),
         "website", "t.domain IS NOT NULL", (("domain", "NULL"),), label="name"),
    Rule("website-cdn", _ODOO.format("16.0-19.0", "addons/website"),
         "website", "t.cdn_activated", (("cdn_activated", "false"),), label="name"),
    Rule("base-url", "a copy's links, portal and reports must not point at production",
         "ir_config_parameter", _param("web.base.url"), (("value", ":local_url"),),
         requires=("key",), label="key"),
    Rule("base-url-freeze", "a frozen base URL would keep production's after login",
         "ir_config_parameter", _param("web.base.url.freeze"), (("value", "'False'"),),
         requires=("key",), label="key"),
    Rule("neutralised-banner", _ODOO.format("16.0-19.0", "addons/web"),
         "ir_ui_view", "t.key = 'web.neutralize_banner' AND NOT t.active",
         (("active", "true"),), requires=("key",), label="key"),
    Rule("neutralised-flag", _ODOO.format("16.0-19.0", "odoo/addons/base"),
         "ir_config_parameter",
         f"{_param('database.is_neutralized')} AND t.value IS DISTINCT FROM 'True'",
         (("value", "'True'"),), requires=("key",), label="key"),
)


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _value(expr: str, local_url: str) -> str:
    return expr.replace(":local_url", _lit(local_url))


def _guard(rule: Rule) -> str:
    """The table and every column of ``rule`` exist (``pg_attribute``: existence must
    not depend on what the connected role may read)."""
    cols = ", ".join(_lit(c) for c in rule.columns)
    return (f"(SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            f"JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema() "
            f"AND c.relkind = 'r' AND c.relname = {_lit(rule.table)} AND a.attnum > 0 AND NOT "
            f"a.attisdropped AND a.attname IN ({cols})) = {len(rule.columns)}")


def _armed(rule: Rule, local_url: str) -> str:
    return " OR ".join(f"t.{c} IS DISTINCT FROM {_value(e, local_url)}" for c, e in rule.sets)


def _mail_sink_block() -> str:
    """One active outgoing server pointing nowhere. Without it Odoo falls back to
    ``smtp_server`` in odoo.conf (``localhost:25`` by default), and a local MTA
    relays real mail. Cloned from an existing row when there is one, so the
    columns each version requires are filled; inserted otherwise."""
    name, host, port = _lit(MAIL_SINK_NAME), _lit(MAIL_SINK_HOST), MAIL_SINK_PORT
    auth_col = ("(SELECT count(*) = 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'ir_mail_server' AND a.attname = 'smtp_authentication' "
                "AND NOT a.attisdropped)")
    return (
        "IF to_regclass('ir_mail_server') IS NOT NULL THEN "
        f"IF EXISTS (SELECT 1 FROM ir_mail_server WHERE name = {name}) THEN "
        f"UPDATE ir_mail_server SET active = true, smtp_host = {host}, smtp_port = {port}, "
        f"smtp_user = NULL, smtp_pass = NULL, sequence = 1 WHERE name = {name}; "
        "ELSIF EXISTS (SELECT 1 FROM ir_mail_server) THEN "
        "INSERT INTO ir_mail_server SELECT (jsonb_populate_record(NULL::ir_mail_server, "
        "to_jsonb(src) || jsonb_build_object('id', nextval(pg_get_serial_sequence('ir_mail_server', "
        f"'id')), 'name', {name}, 'smtp_host', {host}, 'smtp_port', {port}, "
        "'smtp_encryption', 'none', 'smtp_user', NULL, 'smtp_pass', NULL, 'sequence', 1, "
        "'active', true))).* FROM (SELECT * FROM ir_mail_server ORDER BY id LIMIT 1) src; "
        f"ELSIF {auth_col} THEN "
        "INSERT INTO ir_mail_server (name, smtp_host, smtp_port, smtp_encryption, sequence, active, "
        f"smtp_authentication) VALUES ({name}, {host}, {port}, 'none', 1, true, 'login'); "
        "ELSE INSERT INTO ir_mail_server (name, smtp_host, smtp_port, smtp_encryption, sequence, "
        f"active) VALUES ({name}, {host}, {port}, 'none', 1, true); END IF; END IF; "
    )


def apply_sql(local_url: str) -> str:
    """Neutralise the connected database. One statement, so it applies whole or not
    at all; repeatable."""
    blocks = "".join(
        f"IF {_guard(rule)} THEN UPDATE {rule.table} t SET "
        + ", ".join(f"{c} = {_value(e, local_url)}" for c, e in rule.sets)
        + f" WHERE ({rule.where}) AND ({_armed(rule, local_url)}); END IF; "
        for rule in CATALOGUE
    )
    flag = (
        "IF to_regclass('ir_config_parameter') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "
        "ir_config_parameter WHERE key = 'database.is_neutralized') THEN "
        "INSERT INTO ir_config_parameter (key, value) VALUES ('database.is_neutralized', 'True'); "
        "END IF; "
    )
    return f"DO $$ BEGIN {blocks}{_mail_sink_block()}{flag}END $$;"


def guard_sql(local_url: str) -> str:
    """Raises, naming every rule with something still armed, or does nothing. Writes
    nothing; guarded like ``apply_sql``, so it runs on any version."""
    blocks = "".join(
        f"IF {_guard(rule)} THEN SELECT count(*) INTO n FROM {rule.table} t WHERE "
        f"({rule.where}) AND ({_armed(rule, local_url)}); IF n > 0 THEN found := found || "
        f"{_lit(rule.id)} || ' (' || n || ') '; END IF; END IF; "
        for rule in CATALOGUE
    )
    sink = (
        "IF to_regclass('ir_mail_server') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ir_mail_server "
        f"WHERE active AND name = {_lit(MAIL_SINK_NAME)} AND smtp_host = {_lit(MAIL_SINK_HOST)}) THEN "
        "found := found || 'mail-sink (missing) '; END IF; "
    )
    return (
        "DO $$ DECLARE n integer; found text := ''; BEGIN "
        f"{blocks}{sink}"
        "IF found <> '' THEN RAISE EXCEPTION 'the copy can still act on the outside: %', found; "
        "END IF; END $$;"
    )


def columns_sql() -> str:
    """Which catalogue tables and columns exist. Writes nothing."""
    tables = ", ".join(_lit(t) for t in dict.fromkeys(r.table for r in CATALOGUE))
    return ("SELECT c.relname, a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = "
            "a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = "
            "current_schema() AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped "
            f"AND c.relname IN ({tables})")


def applicable(existing: set[tuple[str, str]]) -> list[Rule]:
    """The rules whose table and columns exist, given ``(table, column)`` pairs."""
    return [r for r in CATALOGUE if all((r.table, c) in existing for c in r.columns)]


def check_sql(rules: list[Rule], local_url: str) -> str:
    """One row per rule with something still armed: rule, count, up to five labels.
    Only ``SELECT``; pass only applicable rules."""
    parts = []
    for rule in rules:
        label = f"t.{rule.label}::text" if rule.label else "t.id::text"
        parts.append(
            f"SELECT {_lit(rule.id)}, count(*)::text, coalesce(array_to_string("
            f"(array_agg({label} ORDER BY t.id))[1:5], ', '), '') FROM {rule.table} t "
            f"WHERE ({rule.where}) AND ({_armed(rule, local_url)}) HAVING count(*) > 0"
        )
    if not parts:
        return "SELECT NULL::text, NULL::text, NULL::text WHERE false"
    return " UNION ALL ".join(parts)


def copied_identity_sql() -> str:
    """A copy is a new database for Odoo and its services: fresh ``database.uuid``,
    ``database.secret`` (signs sessions and tokens) and ``database.create_date`` —
    what Odoo's own copy resets (``ir.config_parameter.init(force=True)``)."""
    # md5 of randomness shaped as a UUID: gen_random_uuid() is core only from
    # PostgreSQL 13, and a restore may target an older remote server.
    uuid = ("regexp_replace(md5(random()::text || clock_timestamp()::text), "
            "'(.{8})(.{4})(.{4})(.{4})(.{12})', '\\1-\\2-\\3-\\4-\\5')")
    values = (
        f"('database.uuid', {uuid}), "
        f"('database.secret', {uuid}), "
        "('database.create_date', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))"
    )
    return (
        "INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date) "
        f"SELECT v.key, v.value, 1, now(), 1, now() FROM (VALUES {values}) AS v(key, value) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now();"
    )
