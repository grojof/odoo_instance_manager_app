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

The management menu is grouped into submenus — **Status & health**, **Configuration**, and **Backups &
duplication** — plus a top-level **Delete instance**.

## Status and inspection

Status is **on-demand**: the management menu no longer prints every status table on each iteration. Instead it
offers four selectable entries:

- **Status: locations & names** — the instance's expected paths and derived names.
- **Status: detected resources** — the detected-state table: Linux user, home, config file, systemd service
  (present + active), DB role, data dir, and TLS certificate mode (self-signed / custom-CA / external /
  Let's Encrypt / incomplete / not configured). Optionally connect to PostgreSQL to list databases for
  validation — the listing is **scoped to the instance's DB role** (databases owned by it or named after it),
  not every database on the server.
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

**Update existing configuration** rewrites the instance config, systemd unit, and (optionally) the Nginx
vhost with new values — but first it **backs up** the current config, unit, and vhosts into one private
timestamped directory under `/var/backups/<instance>/config_preupdate/`. The service's autostart state is
preserved.

- The current `odoo.conf` is **merged**, not replaced: `addons_path`, `data_dir`, `logfile`, `http_interface`
  and `without_demo` keep their value, and every key the tool does not write (`smtp_*`, `server_wide_modules`,
  `db_name`, …) is carried over.
- **Nothing is reinstalled**: no apt, clone or pip run (pip could move setuptools under an Odoo that needs it
  pinned).
- The Odoo version is read from the instance's checkout and the domain from its vhost.
- The passwords are kept unless you choose to set new ones; a new DB password is also set on the local role.
- A running service is **restarted**, so the change is live when the plan ends.

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

- Database → `pg_dump -Fc` → `<instance>--<db>--<timestamp>.dump`
- Filestore → gzipped tar → `<instance>--<db>--<timestamp>.filestore.tar.gz`

The name carries the database, so retention keeps N backups of each database. The backup directory is made
private (`700`) and the files are readable by root only: a dump holds password hashes, API keys and mail or
payment secrets.

**Scheduled backups** sets up unattended backups on a systemd timer — see [Scheduled backups](scheduled-backups.md).

> **Credentials are collected once per session:** the first data action (backup / restore / duplicate /
> delete) that needs a database connection prompts for host/port/user/password; subsequent actions offer to
> reuse them. Passwords are read without echo.

## Restore and duplicate — copied vs moved

Both **Restore backup** and **Duplicate instance** apply Odoo's migration semantics and require an exact
confirmation phrase (`RESTORE <instance>` / `DUPLICATE <instance>`):

- **Copied (new UUID on target)** — regenerates `database.uuid` on the target so it is a distinct
  database from the source.
- **Moved (keep UUID)** — keeps the UUID (the database "moves").
- **Neutralize** (optional, recommended) — deactivates `ir_cron`, outgoing mail servers (`ir_mail_server`),
  and `fetchmail_server` in the target so a copy can't send mail or run jobs meant for production.

Guardrails: restore refuses to overwrite an existing target **database**; an existing target **filestore**
requires an explicit overwrite confirmation, and is then moved aside to `<filestore>.replaced-<timestamp>`
rather than deleted. The restored files are handed to the instance user.

### Duplicate instance — replica or refresh

*Duplicate instance* is **existence-aware and end-to-end** (local PostgreSQL; for a remote DB use Backup +
Restore). You pick the **copy method**: *pg_dump → restore* (robust, reassigns ownership to the target role —
recommended for **production → development** with different DB users) or a fast *template* copy, which the
tool only allows when the target role already owns the source database (a template copy keeps the source role
as owner of every table).

- **Target does not exist → replica:** the tool provisions the whole target instance — system user, home, Odoo
  checkout at the **source's version**, virtualenv, `odoo.conf`, systemd service, and optionally Nginx —
  following the **same prompts as a fresh install** (secrets, `list_db`, `dbfilter`, workers, `db_sslmode`,
  wkhtmltopdf), with **auto-suggested non-colliding internal ports**. When it fronts Nginx you must give a
  **domain not already used by another instance** — instances share ports 80/443 and Nginx routes by
  `server_name`, so a duplicate domain would be silently ignored and the replica unreachable. It then seeds the
  target with the source database (+ filestore), optionally **replicates the source venv's Python packages**
  (so addon dependencies beyond `requirements.txt` are present), applies copied/moved + neutralize, and starts
  it.
- **Target exists → refresh in place:** the tool stops the target service, replaces its database and filestore
  from the source, applies the semantics, and restarts — **without** recreating its config or service. This is
  the "keep a dev environment up to date with production" flow. The target's database is dropped only when it
  belongs to the target's own role (from its `odoo.conf`) and you confirm the overwrite; the source instance or
  database can never be the target.

The filestore always lands under the **target** instance's data directory. The template method closes the
source to new sessions, terminates its sessions (brief disconnect), copies, and reopens it even if the copy
fails; the dump method reads the source live.

Every seeded database is **isolated to its owner** (`CONNECT` revoked from `PUBLIC`, granted to the owning
role) so an instance's role can't reach other instances' databases, and the target **data dir is owned by the
target user** so Odoo can create its `sessions`/`filestore`.

### Duplicate database

**Duplicate database** copies just a database (no instance provisioning), with the same copy method and
copied/moved + neutralize semantics, and an optional filestore copy under the current instance's data
directory. It touches no service or config. If the target database already exists it asks for an explicit
overwrite, and it refuses a target database owned by another role. Local PostgreSQL only.

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
| **Delete instance** (in *Manage instances*) | Service, backup timer, config, home, Nginx vhosts, SSL; optionally the database and one database's filestore | `DELETE <instance>` |
| **Remove instances** (main menu → total purge) | Everything above **plus** the Linux user, logs, fail2ban jail, filestore root, the instance's databases, and the PostgreSQL roles | `DELETE-ALL <instance>` |

**Delete instance** keeps the filestores you did not ask to delete. Without a `data_dir` in `odoo.conf`, Odoo
keeps them inside the instance home, so the plan first moves the data dir to
`/var/backups/<instance>/kept-data-dir-<timestamp>` and only then removes the home.

The total purge selects the databases its DB role owns and the one named exactly like the instance (plus those
found in the filestore and any you add). Databases whose name merely starts with the instance name (`shop2`,
`shop_eu` when purging `shop`) are listed as **not selected**; add them yourself if they belong to it. When
another instance connects with the same DB role, the purge says so, selects nothing by owner and keeps the role. Without
admin DB access it performs local cleanup only (skipping DB/role deletion). See the
[removal spec](../../openspec/specs/instance-removal/spec.md) for the full contract.

## Related

- [Installation & provisioning](../installation.md)
- [Fail2ban security](../security/security-fail2ban.md)
- [Configuration reference](../configuration-reference.md)
