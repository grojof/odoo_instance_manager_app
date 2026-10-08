---
type: how-to
title: "Disk usage and backup retention"
description: "See an instance's disk footprint and prune old backups by retention count."
tags: [disk, backups, retention, maintenance]
audience: [operator]
updated: 2026-10-08
---

# Disk usage and backup retention

From **Manage instances → Status & health → Disk usage and cleanup**, the tool shows an instance's disk footprint and prunes
old backups.

## Show disk usage (read-only)

Shows the size of the instance **home**, **data dir** (filestore), **Odoo logs**, and the **backup directory**;
the **free space** of the filesystem holding the data dir; and a listing of the backup files present. It runs
only inspection commands (`du`, `df`, `ls`).

## Prune old backups (retention)

Removes the oldest backups, **keeping the N most recent of each kind per database** — DB dumps (`.dump`) and
filestore archives (`.filestore.tar.gz`) are counted separately. Only names of the exact form
`<instance>--<db>--<timestamp>` are matched, so backups of another instance whose name starts the same way
(`shop_eu` next to `shop`) are never touched. Backups written before the database was part of the name
(`<instance>_<timestamp>`) are pruned as one more group. The most recent are the latest timestamps in the
names, so a backup copied back in later does not count as new. You choose N; the plan is previewed before it
runs. A missing backup directory is a no-op.

## Related

- [Managing existing instances](instance-management.md) — backups are created under *Create backup*.
- [Log rotation](log-rotation.md) — keeps the Odoo log itself bounded.
