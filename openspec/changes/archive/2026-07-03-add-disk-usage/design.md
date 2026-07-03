# Design

Follows the layered pattern: a pure planner for the mutating retention step, a workflow for the read-only
report and the menu.

- `planners.plan_backup_retention(config, backup_dir, keep)` — for each kind (`<inst>_*.dump`,
  `<inst>_*.filestore.tar.gz`) emits `ls -1t <dir>/<pattern> | tail -n +<keep+1> | xargs -r rm -f`, i.e. keep
  the `keep` newest, delete the rest. The dir is shell-quoted; the glob is left unquoted for expansion; the
  instance token is already validated.
- `workflows/diskusage.py`:
  - `_disk_usage_report` — `du -sh` on home / data dir / backup dir, `du -ch <log>*` for the log total,
    `df -Ph` for free space, and an `ls -lht … | grep` backup listing. Read-only.
  - `_cleanup_old_backups` — asks the retention count and runs `plan_backup_retention` through
    `_execute_plan` (preview → confirm → apply). A missing backup dir is a no-op.
  - `manage_disk_usage` — a Ver / Limpiar / Volver submenu; the backup directory is asked once up front.

## Testing

`plan_backup_retention` is pure and unit-tested (two stanzas, `tail -n +N+1`, correct patterns/dir). The
read-only report and interactive cleanup are covered by operator acceptance.

## Out of scope

Automatic/scheduled pruning (retention runs on demand) and cleaning non-backup artifacts beyond the report;
those stay manual or belong to the scheduled-backups capability.
