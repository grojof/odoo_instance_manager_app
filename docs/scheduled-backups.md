---
type: how-to
title: "Scheduled backups"
description: "Run automatic backups of an instance on a systemd timer, with retention."
tags: [backups, systemd, timer, automation]
audience: [operator]
updated: 2026-07-03
---

# Scheduled backups

From **Gestionar instancias → Backups programados**, the tool sets up **unattended** backups of an instance on
a systemd timer.

## Configurar backup programado

Installs, for `odoo-backup-<instance>`:

- a **script** `/usr/local/sbin/odoo-backup-<instance>.sh` that dumps a chosen database atomically with
  `sudo -u postgres pg_dump` and, optionally, tars the filestore, then prunes to your retention count;
- a **service** (`oneshot`) that runs the script;
- a **timer** with your schedule — **Diario** (02:30), **Semanal** (Sun 03:00), or **Mensual** (day 1, 03:30) —
  with `Persistent=true` so a missed run catches up after downtime.

You choose the database, destination directory, whether to include the filestore, and how many backups to keep.

> **Local databases only.** The backup uses `sudo -u postgres pg_dump` (local peer auth), so **no password is
> stored** on disk. For a **remote** database, use the manual *Realizar backup* instead.

## Ver estado

Shows the timer's `systemctl status` and its next scheduled run (read-only).

## Eliminar programación

Disables and stops the timer and deletes the timer, service, and script.

## Related

- [Managing existing instances](instance-management.md) — manual *Realizar backup* / *Restaurar backup*.
- [Disk usage and backup retention](disk-usage.md) — inspect and prune backups on demand.
