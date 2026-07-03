---
type: how-to
title: "Managing existing instances"
description: "Day-2 operations: status, config updates, services, backup/restore, duplicate, and removal."
tags: [management, backup, restore, services, lifecycle]
audience: [operator]
updated: 2026-07-03
---

# Managing existing instances

Once an instance exists under `/opt/odoo`, the **Gestionar instancias** and **Servicios instancias** menus
handle day-2 operations. Instances are discovered automatically; you may also type a known name.

## Status and inspection

**Gestión segura de instancia** opens on a status view that shows the instance's expected paths and a
detected-state table: Linux user, home, config file, systemd service (present + active), DB role, data dir,
and TLS certificate mode (self-signed / custom-CA / external / Let's Encrypt / incomplete / not configured).
Optionally connect to PostgreSQL to list databases for validation.

## Updating configuration

**Actualizar configuración existente** regenerates the instance config, systemd unit, and (optionally) the
Nginx vhost with new values — but first it **backs up** the current config, unit, and vhosts into one
timestamped directory under `/var/backups/<instance>/config_preupdate/`. The service's autostart state is
preserved.

> **Note:** this update **replays the full Odoo base setup** — it re-runs the package install, ensures the
> user/directories, clones the repo if absent, and rebuilds the venv (`pip install -r requirements.txt`) — not
> just a config rewrite. The prompts currently default to class defaults, so review every value before
> confirming to avoid overwriting a working config (e.g. `db_password`).

## Service control

**Servicios instancias** lists instance services with their run state and autostart state, and offers start,
stop, restart, enable-autostart, and disable-autostart. Each action runs the single matching `systemctl`
command through the preview/confirm/apply flow.

## Backups

**Realizar backup** exports the database and/or filestore into a timestamped file in your chosen backup
directory:

- Database → `pg_dump -Fc` → `<instance>_<timestamp>.dump`
- Filestore → gzipped tar → `<instance>_<timestamp>.filestore.tar.gz`

> **Credentials are collected once per session:** the first data action (backup / restore / duplicate /
> delete) that needs a database connection prompts for host/port/user/password; subsequent actions offer to
> reuse them. Passwords are read without echo.

## Restore and duplicate — copied vs moved

Both **Restaurar backup** and **Duplicar instancia** apply Odoo's migration semantics and require an exact
confirmation phrase (`RESTORE <instance>` / `DUPLICAR <instance>`):

- **Copiada (nuevo UUID en destino)** — regenerates `database.uuid` on the target so it is a distinct
  database from the source.
- **Movida (mantener UUID)** — keeps the UUID (the database "moves").
- **Neutralizar** (optional, recommended) — deactivates `ir_cron`, outgoing mail servers (`ir_mail_server`),
  and `fetchmail_server` in the target so a copy can't send mail or run jobs meant for production.

Guardrails: restore refuses to overwrite an existing target **database** (the existence check runs against the
**local** server, so a remote target collision is caught by `createdb` failing rather than the pre-check); an
existing target **filestore** requires an explicit overwrite confirmation. Duplication refuses if the target
home, service, database, or filestore already exists, and copies the DB via `createdb -T <source>`.

> **Duplication scope:** *Duplicar instancia* copies the database and (optionally) the filestore only — the
> duplicated filestore lands under the **target** instance's data directory. It does **not** provision the
> target instance's service, config, or system user; run an install for that separately.

## Repairing Nginx logs & venv packages

- **Reparar logs Nginx de instancia** recreates the per-instance access/error logs with correct ownership
  (`www-data:adm`, mode `640`) and reopens Nginx logs.
- **Rotación de logs** configures and queries a system `logrotate` policy for the instance's Odoo log — see
  [Log rotation](log-rotation.md).
- **Instalar paquetes Python en venv** installs into the instance virtualenv from a selected requirements
  file or an inline package list, running pip as the instance user.

## Removing an instance

Two levels, both phrase-gated:

| Action | Removes | Phrase |
|--------|---------|--------|
| **Eliminar instancia** (in *Gestionar instancias*) | Service, config, home, Nginx vhosts, SSL; optionally the database and filestore | `ELIMINAR <instance>` |
| **Eliminar instancias** (main menu → total purge) | Everything above **plus** the Linux user, logs, filestore root, all `<instance>%` databases, and the PostgreSQL roles | `ELIMINAR-TODO <instance>` |

The total purge discovers databases from the filestore and (with admin DB access) by name prefix, shows a
summary of what it detected, and — without admin DB access — performs local cleanup only (skipping DB/role
deletion). See the [removal spec](../openspec/specs/instance-removal/spec.md) for the full contract.

## Related

- [Installation & provisioning](installation.md)
- [Fail2ban security](security-fail2ban.md)
- [Configuration reference](configuration-reference.md)
