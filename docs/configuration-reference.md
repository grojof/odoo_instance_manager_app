---
type: reference
title: "Configuration reference"
description: "InstanceConfig fields, defaults, validation patterns, and every path derived from an instance name."
tags: [reference, configuration, paths]
audience: [operator, contributor]
updated: 2026-07-04
---

# Configuration reference

An instance is described by `InstanceConfig` (`instance_manager/models.py`). Most paths are **derived** from
the instance name, so a single name determines the whole layout.

## Fields

| Field | Default | Notes |
|-------|---------|-------|
| `instance` | — (required) | Instance name; drives every derived path. Validated (see below). |
| `version` | `18` | Odoo major version. Drives version-adaptive rendering (`gevent_port` vs `longpolling_port`, Nginx live-chat location). |
| `repo_branch` | `18.0` | Git branch cloned from `github.com/odoo/odoo`. |
| `domain` | `odooprodserver.local` | Public server name for Nginx vhosts and TLS subject. |
| `http_port` | `8069` | Internal Odoo HTTP port (auto-suggested to avoid collisions). |
| `gevent_port` | `8072` | Internal live-chat/bus port. Written as `gevent_port` (Odoo ≥ 16) or `longpolling_port` (≤ 15). |
| `db_host` | `127.0.0.1` | PostgreSQL host; local values skip remote role handling and `db_sslmode`. |
| `db_port` | `5432` | PostgreSQL port. |
| `db_user` | `""` → `instance` | DB role; the **identifier** defaults to the instance name if blank. |
| `db_password` | `""` → **generated** | DB password; a blank value gets a **strong random secret** (never the instance name). |
| `db_name` | `""` | Optional, used for validations and the default `dbfilter`. |
| `app_server_ip` | `127.0.0.1` | IP allowed in the `pg_hba` rule for remote DB access (no firewall/UFW rule is added). |
| `odoo_admin_passwd` | `""` → **generated** | Odoo master password; a blank value gets a **strong random secret** (never the instance name). |
| `list_db` | `False` | Whether the web database manager is exposed. `False` is the production-recommended default. |
| `dbfilter` | `""` → `^<db_name>$` | Binds the instance to its database(s); a blank value resolves to an exact match on `db_name` (or `^%d$`). |
| `db_sslmode` | `""` | Written **only for a remote `db_host`** (recommended `require`). Local hosts keep Odoo's default. |
| `workers` | `2` → derived | HTTP workers. Provisioning derives `(cpu*2)+1`, capped by RAM; the operator can override. |
| `max_cron_threads` | `1` → derived | Cron worker threads (2 when ≥ 4 CPU). |
| `limit_memory_soft` / `limit_memory_hard` | `2 GiB` / `2.5 GiB` | Per-worker soft/hard memory ceilings. |
| `limit_request` | `8192` | Max requests handled before a worker is recycled. |
| `limit_time_cpu` / `limit_time_real` | `3600` / `7200` | Per-request CPU/wall-clock limits (seconds). |
| `base_instances_dir` | `/opt/odoo` | Class-level base directory for all instances. |

`normalize_defaults()` fills only the blank **DB user** (an identifier) with the instance name.
`ensure_strong_secrets()` fills a blank **DB password** and **master password** with a strong random value
(`secrets.token_urlsafe`) — secrets never fall back to the guessable instance name. During installation the
prompts offer the generated secret as the accepted-by-default value and warn if the operator chooses the
instance name. See [Installing and provisioning instances](installation.md#production-hardening).

## Validation

Identifiers are checked by `validate_identifiers()` **before** any command is built:

| Value | Pattern | Meaning |
|-------|---------|---------|
| `instance` | `^[a-z][a-z0-9_]{0,31}$` | Lowercase first letter, then `[a-z0-9_]`, max 32 chars. |
| `db_user` | `^[a-z_][a-z0-9_]{0,62}$` | PostgreSQL identifier, max 63 chars. |

## Derived paths

For an instance named `<instance>` with domain `<domain>`:

| Property | Value |
|----------|-------|
| `odoo_user` | `<instance>` |
| `odoo_home` | `/opt/odoo/<instance>` |
| `odoo_conf_dir` | `/etc/odoo/<instance>` |
| `odoo_conf_file` | `/etc/odoo/<instance>/<instance>.conf` |
| `odoo_service` | `<instance>` (systemd unit) |
| `odoo_log_file` | `/var/log/odoo/<instance>.log` |
| `nginx_http_name` | `<instance>-http.conf` |
| `nginx_https_name` | `<instance>-https.conf` |
| `nginx_ssl_dir` | `/etc/nginx/ssl/<instance>` |
| `ssl_cert_file` | `<ssl_dir>/<domain_token>.server.crt` |
| `ssl_key_file` | `<ssl_dir>/<domain_token>.server.key` |
| `ssl_intermediate_file` | `<ssl_dir>/<domain_token>.intermediate.crt` |
| `ssl_fullchain_file` | `<ssl_dir>/<domain_token>.fullchain.crt` |

`domain_token` is the lowercased domain with `*` → `wildcard` and any other unsafe character replaced by `_`.

## Generated instance config (excerpt)

`planners._odoo_conf_content` writes (among others): `admin_passwd` (a strong generated secret unless the
operator set one), `list_db = False` (production-recommended; the operator may opt into `True` after a
warning), `dbfilter`, `proxy_mode = True`, `http_interface = 127.0.0.1`, the live-chat port under
`gevent_port`/`longpolling_port` per the Odoo major, derived `workers`/`max_cron_threads`, `limit_request`
and memory/time limits, `db_sslmode` when the DB host is remote, `logfile = /var/log/odoo/<instance>.log`,
and an `addons_path` of `<home>/odoo/addons,<home>/addons-oca,<home>/addons-custom`.

> **Security note:** the recommended defaults are secure — `list_db = False`, a strong random master
> password, a `dbfilter`, and `db_sslmode = require` for remote databases. The operator can still choose the
> convenient options (exposed manager, chosen password) after an explicit warning, and the current posture is
> surfaced by the **Status ▸ Security & production** view and the server-audit report.

## Related

- [Architecture](architecture.md) — where these values are consumed.
- [Glossary](glossary.md) — terms used throughout.
