---
type: how-to
title: "Disk usage and backup retention"
description: "See an instance's disk footprint and prune old backups by retention count."
tags: [disk, backups, retention, maintenance]
audience: [operator]
updated: 2026-07-03
---

# Disk usage and backup retention

From **Gestionar instancias → Uso de disco y limpieza**, the tool shows an instance's disk footprint and prunes
old backups.

## Ver uso de disco (read-only)

Shows the size of the instance **home**, **data dir** (filestore), **Odoo logs**, and the **backup directory**;
the **free space** of the filesystem holding the data dir; and a listing of the backup files present. It runs
only inspection commands (`du`, `df`, `ls`).

## Limpiar backups antiguos (retención)

Removes the oldest backups, **keeping the N most recent of each kind** — DB dumps (`*.dump`) and filestore
archives (`*.filestore.tar.gz`) are counted separately. You choose N; the plan is previewed before it runs, so
you see exactly which files will be deleted. A missing backup directory is a no-op.

## Related

- [Managing existing instances](instance-management.md) — backups are created under *Realizar backup*.
- [Log rotation](log-rotation.md) — keeps the Odoo log itself bounded.
