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

### Avoiding double rotation

The generated `odoo.conf` sets `logrotate = True` (Odoo's own rotator). Running that **and** system logrotate
on the same file rotates it twice, so Configure detects the flag, warns, and offers to set `logrotate = False`
in the config. If you accept, **restart the Odoo service** (from *Servicios instancias → Reiniciar*) for it to
take effect.

## Query

**Consultar rotación actual** is read-only and shows:

- the Odoo log path and current log file sizes,
- whether a system logrotate policy exists and its full contents,
- a `logrotate -d` dry-run preview of what would rotate,
- the state of Odoo's built-in `logrotate` flag.

## Nginx logs

This capability manages the **Odoo** log only. Per-instance Nginx logs
(`/var/log/nginx/<instance>.{access,error}.log`) are already rotated by the distribution's own
`/etc/logrotate.d/nginx`; the query notes this so you don't double-configure them.

## Related

- [Managing existing instances](instance-management.md)
- [Configuration reference](configuration-reference.md) — the `logfile` / `logrotate` config keys.
- [Log-rotation spec](../openspec/specs/log-rotation/spec.md) — the behavior contract.
