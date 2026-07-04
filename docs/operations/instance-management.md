---
type: how-to
title: "Managing existing instances"
description: "Day-2 operations: status, config updates, services, backup/restore, duplicate, and removal."
tags: [management, backup, restore, services, lifecycle]
audience: [operator]
updated: 2026-07-04
---

# Managing existing instances

Once an instance exists under `/opt/odoo`, the **Manage instances** and **Instance services** menus
handle day-2 operations. Instances are discovered automatically; you may also type a known name.

## Status and inspection

Status is **on-demand**: the management menu no longer prints every status table on each iteration. Instead it
offers four selectable entries:

- **Status: locations & names** — the instance's expected paths and derived names.
- **Status: detected resources** — the detected-state table: Linux user, home, config file, systemd service
  (present + active), DB role, data dir, and TLS certificate mode (self-signed / custom-CA / external /
  Let's Encrypt / incomplete / not configured). Optionally connect to PostgreSQL to list databases for
  validation.
- **Status: config values** — useful keys read from the instance's `odoo.conf`.
- **Status: security & production** — the production-posture view (below).

### Security & production posture

**Status: security & production** flags each posture check `OK` / `WARN` / `INFO` with a reason, read from the
instance's `odoo.conf` plus host facts (no mutation):

- **Database manager (`list_db`)** — exposed vs disabled.
- **Master / DB passwords** — guessable when they equal the instance name; a **hashed** master password is
  treated as `OK`.
- **wkhtmltopdf** — presence and version (patched vs un-patched).
- **workers** — sizing against the detected CPU count.
- **`db_sslmode`** — for a remote DB host; local hosts are treated as `OK`.
- **dbfilter** — set vs unset.

## Updating configuration

**Update existing configuration** regenerates the instance config, systemd unit, and (optionally) the
Nginx vhost with new values — but first it **backs up** the current config, unit, and vhosts into one
timestamped directory under `/var/backups/<instance>/config_preupdate/`. The service's autostart state is
preserved.

> **Note:** this update **replays the full Odoo base setup** — it re-runs the package install, ensures the
> user/directories, clones the repo if absent, and rebuilds the venv (`pip install -r requirements.txt`) — not
> just a config rewrite. The prompts now **read and preserve the instance's current credentials and
> production-posture settings** from its `odoo.conf` (rather than resetting them to class defaults), but still
> review every value before confirming.

## Health check

**Health check** runs a read-only check of the instance — systemd service, local HTTP
response, database connectivity, and disk usage — flagging any problems. See
[Instance health check](health-check.md).

## Service control

**Instance services** lists instance services with their run state and autostart state, and offers start,
stop, restart, enable-autostart, and disable-autostart. Each action runs the single matching `systemctl`
command through the preview/confirm/apply flow.

## Backups

**Create backup** exports the database and/or filestore into a timestamped file in your chosen backup
directory:

- Database → `pg_dump -Fc` → `<instance>_<timestamp>.dump`
- Filestore → gzipped tar → `<instance>_<timestamp>.filestore.tar.gz`

**Scheduled backups** sets up unattended backups on a systemd timer — see [Scheduled backups](scheduled-backups.md).

> **Credentials are collected once per session:** the first data action (backup / restore / duplicate /
> delete) that needs a database connection prompts for host/port/user/password; subsequent actions offer to
> reuse them. Passwords are read without echo.

## Restore and duplicate — copied vs moved

Both **Restore backup** and **Duplicate instance** apply Odoo's migration semantics and require an exact
confirmation phrase (`RESTORE <instance>` / `DUPLICAR <instance>`):

- **Copied (new UUID on target)** — regenerates `database.uuid` on the target so it is a distinct
  database from the source.
- **Moved (keep UUID)** — keeps the UUID (the database "moves").
- **Neutralize** (optional, recommended) — deactivates `ir_cron`, outgoing mail servers (`ir_mail_server`),
  and `fetchmail_server` in the target so a copy can't send mail or run jobs meant for production.

Guardrails: restore refuses to overwrite an existing target **database** (the existence check runs against the
**local** server, so a remote target collision is caught by `createdb` failing rather than the pre-check); an
existing target **filestore** requires an explicit overwrite confirmation. Duplication refuses if the target
home, service, database, or filestore already exists, and copies the DB via `createdb -T <source>`.

> **No manual stop needed:** a template copy requires no other sessions on the source database, so duplication
> automatically **frees the source** — it blocks new connections, terminates existing sessions, copies, and
> **re-enables** the source afterward (even if the copy fails). The source instance is briefly disconnected
> during the copy, exactly like Odoo's own database-manager duplicate. It runs with the instance's own
> database role — no superuser needed.

> **Duplication scope:** *Duplicate instance* copies the database and (optionally) the filestore only — the
> duplicated filestore lands under the **target** instance's data directory. It does **not** provision the
> target instance's service, config, or system user; run an install for that separately.

## Repairing Nginx logs & venv packages

- **Repair instance Nginx logs** recreates the per-instance access/error logs with correct ownership
  (`www-data:adm`, mode `640`) and reopens Nginx logs.
- **Log rotation** configures and queries a system `logrotate` policy for the instance's Odoo log — see
  [Log rotation](log-rotation.md).
- **Install Python packages in the venv** installs into the instance virtualenv from a selected requirements
  file or an inline package list, running pip as the instance user.
- **Addon inventory** lists modules by origin (core/OCA/custom) with versions and installed state — see
  [Addon inventory](addon-inventory.md).
- **Disk usage and cleanup** shows the instance footprint and prunes old backups by retention — see
  [Disk usage and backup retention](disk-usage.md).

## Removing an instance

Two levels, both phrase-gated:

| Action | Removes | Phrase |
|--------|---------|--------|
| **Delete instance** (in *Manage instances*) | Service, config, home, Nginx vhosts, SSL; optionally the database and filestore | `DELETE <instance>` |
| **Remove instances** (main menu → total purge) | Everything above **plus** the Linux user, logs, filestore root, all `<instance>%` databases, and the PostgreSQL roles | `DELETE-ALL <instance>` |

The total purge discovers databases from the filestore and (with admin DB access) by name prefix, shows a
summary of what it detected, and — without admin DB access — performs local cleanup only (skipping DB/role
deletion). See the [removal spec](../../openspec/specs/instance-removal/spec.md) for the full contract.

## Related

- [Installation & provisioning](../installation.md)
- [Fail2ban security](../security/security-fail2ban.md)
- [Configuration reference](../configuration-reference.md)
