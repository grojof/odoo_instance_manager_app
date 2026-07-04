---
type: how-to
title: "Installing and provisioning instances"
description: "Run the manager and provision an Odoo instance, PostgreSQL, or both, including Nginx and TLS."
tags: [installation, provisioning, nginx, tls]
audience: [operator]
updated: 2026-07-04
---

# Installing and provisioning instances

This guide covers the **Installation menu** and its provisioning modes. All actions preview their command
plan before applying — see [Architecture](architecture.md).

## Prerequisites

- A **Debian/Ubuntu (apt) family** server, validated on Ubuntu 24.04. Configuration is version-adaptive, so
  other apt releases work too — see [supported platforms](platforms.md).
- Python 3.12+ available as `python3` (the tool uses 3.12 syntax).
- Run as root: the tool refuses to start otherwise.

```bash
sudo python3 odoo_instance_manager.py
```

## Provisioning modes

From **Installation menu** you choose one of three modes:

| Mode | What it does |
|------|--------------|
| **Install Odoo instance** | Ensures the DB role/login, runs the Odoo base setup, and optionally configures Nginx. Does **not** install PostgreSQL. |
| **Install PostgreSQL (without Odoo)** | Installs and enables PostgreSQL, ensures the instance role, validates login, and optionally opens remote access. |
| **Install Odoo instance + PostgreSQL** | DB setup (with remote access) followed by the Odoo base setup, and optionally Nginx. |

## What the Odoo base setup does

For an instance named `<instance>` (see the [configuration reference](configuration-reference.md) for every
derived path):

1. Installs OS build dependencies and the PostgreSQL client.
2. Creates the system user `<instance>` and the directory layout under `/opt/odoo/<instance>`
   (`odoo`, `addons-oca`, `addons-custom`) plus `/etc/odoo/<instance>` and `/var/log/odoo`.
3. Clones Odoo at the requested branch (only if absent) and builds a virtualenv with `requirements.txt`.
4. Writes `/etc/odoo/<instance>/<instance>.conf` (mode `640`, owner `root:<instance>`).
5. Writes the systemd unit and reloads systemd.
6. Enables + starts the service, or just starts it, depending on your autostart choice.

### Port suggestion

When collecting the config, the tool suggests HTTP and gevent ports that avoid ports already used by active
listeners, existing Odoo configs, and existing Nginx vhosts — so co-located instances don't collide. You can
override the suggestion.

### Database role

The tool ensures the instance's PostgreSQL role exists with `LOGIN CREATEDB`, **creating it only if missing**
and never changing an existing role's password. For a **remote** DB host it skips role creation (no admin
credentials assumed) and only validates the configured user's login.

## Production hardening

Provisioning is **secure by default through informed choice**: each prompt recommends the production-safe
option and offers it as the accepted-by-default value, but the operator can always override it after an
explicit warning.

- **Master / DB passwords.** A strong random secret is generated and offered as the Enter-to-accept default;
  record it when shown. Typing the instance name instead is warned as guessable (the master password guards
  the database manager).
- **Database manager (`list_db`).** Defaults to `False` (recommended); choosing `True` is warned because the
  manager becomes reachable over HTTP, guarded only by the master password. With `list_db = False` you create
  the first database via CLI (`odoo-bin -d <db> -i base --stop-after-init`) or by temporarily re-enabling it.
- **dbfilter.** Written to bind the host to its database(s); the default is an exact match on the DB name.
- **Workers / memory.** Derived from detected CPU/RAM as `(cpu*2)+1`, capped by RAM (with per-worker memory
  and request limits). The operator can override the suggested values.
- **`db_sslmode`.** For a **remote** DB host it defaults to `require` (offered `require` / `verify-full` /
  `prefer` / `disable`, with a warning for the cleartext-capable modes). Local hosts are left untouched.
- **wkhtmltopdf.** Odoo PDF reports (invoices, quotations, …) require wkhtmltopdf. A three-way choice:
  the **patched 0.12.6** build (recommended, checksum-verified, selected by the detected OS codename), the
  **distribution package** (un-patched, reduced report fidelity), or **skip** (warned that PDF reports will
  fail until it is installed).

The resulting posture is later surfaced by the **Status: security & production** view and the
[server-audit report](server-audit.md). See also the
[configuration reference](configuration-reference.md).

## Nginx and TLS

After the base setup you choose an Nginx mode: **leave untouched**, **HTTP**, or **HTTPS**. HTTP and HTTPS are
mutually exclusive — enabling one removes the other's enabled vhost, then the plan runs `nginx -t` and reloads.

For HTTPS you pick a certificate strategy:

| Strategy | Behavior |
|----------|----------|
| **Leave certificates untouched** | Adds no certificate commands. |
| **Self-signed** | Reuses an existing key/fullchain or generates a 2048-bit self-signed cert for the domain. |
| **Let's Encrypt (managed externally)** | Adds no certificate commands — you manage LE outside the tool. |
| **Copy your own certificates** | Installs your CRT/KEY (+ optional intermediate), builds the fullchain, and **validates that the key matches the certificate** before Nginx is reconfigured. |

## If an install fails

If applying an install plan errors partway, the tool runs a **best-effort cleanup** of that instance's
residues (service, config, home, Nginx vhosts, SSL dir, and — when the run created it — the DB role) so you
can retry cleanly. The original error is then re-raised.

## Related

- [Configuration reference](configuration-reference.md) — every field and derived path.
- [Instance management](operations/instance-management.md) — day-2 operations once an instance exists.
