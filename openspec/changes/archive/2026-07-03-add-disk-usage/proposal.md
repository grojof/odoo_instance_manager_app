# Add disk usage report and backup retention

## Why

Instances and their backups accumulate on disk over time (filestore growth, old dumps, rotated logs). The tool
had no way to see an instance's footprint or to prune old backups, so operators had to do it by hand and disks
could silently fill.

## What changes

A new **disk-usage** capability, from *Gestionar instancias → Uso de disco y limpieza*:

- **Ver uso de disco** (read-only) — sizes of the home, data dir (filestore), Odoo logs, and backup directory;
  the free space of the data-dir filesystem; and a listing of present backup files.
- **Limpiar backups antiguos (retención)** — remove the oldest backups keeping the N most recent of each kind
  (DB dumps and filestore archives), through the standard preview/confirm/apply flow.

## Impact

- New spec: `disk-usage`.
- New code: `planners.plan_backup_retention` (pure), `workflows/diskusage.py` (`manage_disk_usage`), wired into
  `manage_existing_instance`.
- New planner test; docs added. No new dependency (`du`/`df`/`ls` are coreutils).
