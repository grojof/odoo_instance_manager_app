# Production-safe defaults, optional wkhtmltopdf, and an on-demand status audit

## Why

The tool provisions a technically sound Odoo Community stack (dedicated user, isolated venv, reverse
proxy, systemd, UFW, fail2ban, backups), but three install-time defaults do not match Odoo's own
production guidance, and the management status view has become an unreadable wall of tables:

- **Guessable secrets.** Blank `admin_passwd` (the master password) and `db_password` silently fall
  back to the **instance name** (`models.py:97-104`). Odoo's deploy guide says the master password
  "should be set to a randomly generated value". A guessable master password is the key to the DB
  manager.
- **DB manager exposed.** `odoo.conf` ships `list_db = True` (`planners.py:59`). Odoo "strongly
  recommends" `--no-database-list` / `list_db = False` for internet-facing systems, plus a
  `dbfilter`.
- **Static, un-tuned runtime.** `workers = 4` is hardcoded regardless of the host's CPU/RAM
  (`planners.py:70`); Odoo's formula is `workers = (cpu * 2) + 1` with memory sized per worker.
  `db_sslmode` is never set even when the DB host is remote, so Odoo↔PostgreSQL traffic can cross the
  network unencrypted.
- **No wkhtmltopdf.** The dependency list installs wkhtmltopdf's font prerequisites but not the binary
  (`planners.py:513-518`); without the Qt-patched 0.12.6 build, PDF reports (invoices, quotations)
  fail or degrade.
- **Status overload.** `manage_existing_instance` re-renders three full tables on **every** menu
  iteration (`manage.py:482-484`), so the operator cannot see what changed.
- **Version-brittle templates.** The odoo.conf and nginx vhost hardcode post-Odoo-16 shapes
  (`gevent_port`, `/websocket`) and the nginx 1.24 `listen … http2` form. An Odoo ≤ 15 install would
  get a broken live-chat/bus location, and a future nginx ≥ 1.25.1 would emit deprecation warnings —
  the tool should adapt to what it detects, not to a single assumed stack.

The design intent — easy first-run setup, hardened afterwards — is legitimate. This change keeps that
intent but flips the *recommended* path to secure, makes the convenient/weak path an **informed,
warned choice**, and surfaces the resulting posture in the audit.

## What changes

Behavior + specs across three capabilities. Recommend-secure-by-default, always allow an informed
opt-out, and audit the outcome.

- **instance-provisioning**
  - **Safe configuration defaults (MODIFIED):** blank `admin_passwd`/`db_password` default to a
    freshly generated strong secret (stdlib `secrets`), never the instance name; a weak value
    (including the instance name) is allowed only after an explicit risk warning. The DB **user** may
    still default to the instance name (an identifier, not a secret).
  - **Database manager exposure control (ADDED):** operator chooses `list_db`; recommended default
    `False`; keeping it `True` requires an acknowledged warning.
  - **Production performance tuning (ADDED):** `workers` derived from detected CPU (`(cpu*2)+1`),
    capped by detected RAM; `limit_memory_soft/hard` scaled per worker; operator can override.
    Detection lives in the execution layer, planners stay pure.
  - **Database filter (ADDED):** write a `dbfilter` bound to the instance's DB name (or host).
  - **PostgreSQL SSL mode for remote databases (ADDED):** when the DB host is remote, set
    `db_sslmode` (default `require`); leave local hosts untouched.
  - **Optional wkhtmltopdf provisioning (ADDED):** offer the checksum-verified patched 0.12.6 build
    (recommended), the distro package (reduced-fidelity), or skip (warned).
- **instance-configuration**
  - **Instance status inspection (MODIFIED):** split the single dump into separate, on-demand views
    (locations / detected state / config values); stop auto-rendering the full status on every menu
    iteration.
  - **Security and production posture audit (ADDED):** an on-demand view flagging `list_db`,
    guessable default secrets, wkhtmltopdf presence/version, worker sizing, remote `db_sslmode`, and
    `dbfilter`.
- **server-audit**
  - **Production posture reporting (ADDED):** the read-only whole-server report surfaces the same
    posture per instance plus the host wkhtmltopdf version.
- **instance-provisioning**
  - **Environment detection and version-adaptive configuration (ADDED):** instead of assuming Ubuntu
    24.04 / nginx 1.24 / a fixed Odoo release, the tool detects the OS family + codename, the nginx
    version, the PostgreSQL version, and uses the operator-supplied Odoo major, then renders
    version-correct configuration (or warns when a component is unsupported).
- **web-proxy-tls**
  - **Proxy vhost contents (MODIFIED):** the generated vhost adapts to the detected **nginx version**
    (`listen … http2` on nginx < 1.25.1, `http2 on;` on ≥ 1.25.1) and to the **Odoo major** (live-chat
    location `/websocket` on Odoo ≥ 16, `/longpolling/poll` on ≤ 15).

This removes the hard tie to Ubuntu 24.04. Detection is cheap (one probe per component) and lives in
the execution layer so the planners stay pure. The one axis deliberately **not** expanded is
PostgreSQL *performance* tuning of `postgresql.conf` (shared_buffers, etc.) — a separate, larger
concern; here PostgreSQL detection only feeds validation/audit and confirms `scram-sha-256` support.

## Impact

- Specs: instance-provisioning, instance-configuration, server-audit, web-proxy-tls.
- Code (behavioral): `models.py`/`prompts.py` (secret generation + warned opt-out), `planners.py`
  (`_odoo_conf_content` gains `list_db`, `dbfilter`, `db_sslmode`, computed workers/memory; base setup
  gains optional wkhtmltopdf step), `system.py` (CPU/RAM probes, wkhtmltopdf version probe), install &
  manage workflows (new prompts + posture view + status split), report workflow (posture rows).
- Docs: configuration-reference, installation, instance-management, server-audit, security pages, and
  the README map, updated in lockstep; `CHANGELOG.md` `[Unreleased]`. Plus a **"what the utility offers
  & supported platforms"** overview (capability list + OS/nginx/PostgreSQL/Odoo support matrix), and a
  pass making the docs **English-canonical** — the pages currently quote Spanish UI menu labels, which
  must become the English labels now that English is the default UI (i18n #31/#32).
- Backward compatibility: existing instances are untouched until reconfigured; the posture audit is
  read-only and flags them. Recommended defaults change for **new** installs; the operator can still
  reproduce the old behavior via the warned opt-out.
