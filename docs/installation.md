---
type: how-to
title: "Installing and provisioning instances"
description: "Run the manager and provision an Odoo instance, PostgreSQL, or both, including Nginx and TLS."
tags: [installation, provisioning, nginx, tls]
audience: [operator]
updated: 2026-07-03
---

# Installing and provisioning instances

This guide covers the **Menú de instalación** and its provisioning modes. All actions preview their command
plan before applying — see [Architecture](architecture.md).

## Prerequisites

- Ubuntu 24.04 server.
- Python 3 available as `python3`.
- Run as root: the tool refuses to start otherwise.

```bash
sudo python3 odoo_instance_manager.py
```

## Provisioning modes

From **Menú de instalación** you choose one of three modes:

| Mode | What it does |
|------|--------------|
| **Instalar instancia Odoo** | Ensures the DB role/login, runs the Odoo base setup, and optionally configures Nginx. Does **not** install PostgreSQL. |
| **Instalar PostgreSQL (sin Odoo)** | Installs and enables PostgreSQL, ensures the instance role, validates login, and optionally opens remote access. |
| **Instalar instancia Odoo + PostgreSQL** | DB setup (with remote access) followed by the Odoo base setup, and optionally Nginx. |

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

## Nginx and TLS

After the base setup you choose an Nginx mode: **leave untouched**, **HTTP**, or **HTTPS**. HTTP and HTTPS are
mutually exclusive — enabling one removes the other's enabled vhost, then the plan runs `nginx -t` and reloads.

For HTTPS you pick a certificate strategy:

| Strategy | Behavior |
|----------|----------|
| **No tocar certificados** | Adds no certificate commands. |
| **Autofirmado** | Reuses an existing key/fullchain or generates a 2048-bit self-signed cert for the domain. |
| **Let's Encrypt (externo)** | Adds no certificate commands — you manage LE outside the tool. |
| **Copiar certificados propios** | Installs your CRT/KEY (+ optional intermediate), builds the fullchain, and **validates that the key matches the certificate** before Nginx is reconfigured. |

## If an install fails

If applying an install plan errors partway, the tool runs a **best-effort cleanup** of that instance's
residues (service, config, home, Nginx vhosts, SSL dir, and — when the run created it — the DB role) so you
can retry cleanly. The original error is then re-raised.

## Related

- [Configuration reference](configuration-reference.md) — every field and derived path.
- [Instance management](instance-management.md) — day-2 operations once an instance exists.
