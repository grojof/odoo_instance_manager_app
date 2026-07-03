---
type: reference
title: "Configuration reference"
description: "InstanceConfig fields, defaults, validation patterns, and every path derived from an instance name."
tags: [reference, configuration, paths]
audience: [operator, contributor]
updated: 2026-07-03
---

# Configuration reference

An instance is described by `InstanceConfig` (`instance_manager/models.py`). Most paths are **derived** from
the instance name, so a single name determines the whole layout.

## Fields

| Field | Default | Notes |
|-------|---------|-------|
| `instance` | — (required) | Instance name; drives every derived path. Validated (see below). |
| `version` | `18` | Odoo major version (label only). |
| `repo_branch` | `18.0` | Git branch cloned from `github.com/odoo/odoo`. |
| `domain` | `odooprodserver.local` | Public server name for Nginx vhosts and TLS subject. |
| `http_port` | `8069` | Internal Odoo HTTP port (auto-suggested to avoid collisions). |
| `gevent_port` | `8072` | Internal gevent/websocket port. |
| `db_host` | `127.0.0.1` | PostgreSQL host; local values skip remote role handling. |
| `db_port` | `5432` | PostgreSQL port. |
| `db_user` | `""` → `instance` | DB role; defaults to the instance name if blank. |
| `db_password` | `""` → `instance` | DB password; defaults to the instance name if blank. |
| `db_name` | `""` | Optional, used for validations only. |
| `app_server_ip` | `127.0.0.1` | IP allowed in the `pg_hba` rule for remote DB access (no firewall/UFW rule is added). |
| `odoo_admin_passwd` | `""` → `instance` | Odoo master password; defaults to the instance name if blank. |
| `base_instances_dir` | `/opt/odoo` | Class-level base directory for all instances. |

Blank `db_user` / `db_password` / `odoo_admin_passwd` are filled with the instance name during
`normalize_defaults()`.

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

`planners._odoo_conf_content` writes (among others): `admin_passwd` (defaults to the instance name),
`list_db = True` (the database manager is reachable — restrict it at the proxy or change this on public
deployments), `proxy_mode = True`, `http_interface = 127.0.0.1`, `workers = 4`, `max_cron_threads = 2`,
memory/time limits, `logfile = /var/log/odoo/<instance>.log`, and an `addons_path` of
`<home>/odoo/addons,<home>/addons-oca,<home>/addons-custom`.

> **Security note:** `list_db = True` combined with an `admin_passwd` that defaults to the instance name means
> the DB manager is exposed with a guessable master password. Set a strong `admin_passwd` and consider
> `list_db = False` for internet-facing instances.

## Related

- [Architecture](architecture.md) — where these values are consumed.
- [Glossary](glossary.md) — terms used throughout.
