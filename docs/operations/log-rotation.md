---
type: how-to
title: "Log rotation"
description: "Configure and query system logrotate for an instance's Odoo log."
tags: [logs, logrotate, maintenance]
audience: [operator]
updated: 2026-07-03
---

# Log rotation

From **Gestionar instancias → Rotación de logs**, the tool configures and inspects a **system `logrotate`**
policy for an instance's Odoo log (`/var/log/odoo/<instance>.log`).

## Configure

**Configurar rotación (system logrotate)** writes `/etc/logrotate.d/odoo-<instance>` with a policy you choose:

- **Frequency** — `weekly` (default), `daily`, or `monthly`.
- **Retention** — how many rotated files to keep (default 14).
- **Compression** — gzip the rotated files (adds `compress` + `delaycompress`).
- **Size threshold** (optional) — also rotate when the log exceeds a size (e.g. `50M`, `1G`).

The policy uses **`copytruncate`**, so Odoo keeps writing to the same file and does **not** need a restart. An
`su <instance> <instance>` directive lets logrotate rotate the instance-owned log safely. The plan installs
`logrotate` if missing and validates the file with `logrotate -d` before finishing.

Log rotation is also offered **at install time** (recommended, default yes), so a fresh instance starts with a
rotation policy in place.

### Obsolete `logrotate` conf key

Odoo's built-in `logrotate` option was **removed in Odoo 13**, so the generated `odoo.conf` no longer sets it.
If an older instance's `odoo.conf` still has a `logrotate` key, Configure detects it (it is an ignored no-op)
and offers to delete the line — no restart needed.

## Query

**Consultar rotación actual** is read-only and shows:

- whether rotation of the Odoo log is **ACTIVA** (a system logrotate policy covers it) or **INACTIVA**,
- the Odoo log path and current log file sizes,
- whether a system logrotate policy exists and its full contents,
- a `logrotate -d` dry-run preview of what would rotate,
- a note if the `odoo.conf` still carries the obsolete `logrotate` key.

## Nginx logs

On a standard Ubuntu, per-instance Nginx logs (`/var/log/nginx/<instance>.{access,error}.log`) are already
rotated by the distribution's own `/etc/logrotate.d/nginx` (`/var/log/nginx/*.log`), so the tool **detects
that coverage and leaves them alone** to avoid double rotation.

If that coverage is **absent**, Configure offers to include the instance's Nginx logs, rotating them with the
modern Nginx-idiomatic method — `create 0640 www-data adm` + a `postrotate` that reopens Nginx via
`kill -USR1 $(cat /run/nginx.pid)` (**not** `copytruncate`: Nginx reopens on signal, so no lines are lost).
The Odoo log keeps `copytruncate` because Odoo has no log-reopen signal — the right method per service.

**Query** reports who rotates the Nginx logs: the distribution's logrotate, this tool's policy, or neither.

## Related

- [Managing existing instances](instance-management.md)
- [Configuration reference](../configuration-reference.md) — the `logfile` config key.
- [Log-rotation spec](../../openspec/specs/log-rotation/spec.md) — the behavior contract.
