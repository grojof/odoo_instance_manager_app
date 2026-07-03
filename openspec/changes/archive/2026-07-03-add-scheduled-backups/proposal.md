# Add scheduled automated backups

## Why

Backups were manual only. Production instances need them to run unattended on a schedule — the most common
operational gap.

## What changes

A new **scheduled-backups** capability, from *Gestionar instancias → Backups programados*:

- **Configurar** — install a systemd `service` + `timer` that runs a backup script for the instance: an atomic
  `sudo -u postgres pg_dump` of a chosen database (local peer auth — no password in unit files) and, optionally,
  a filestore tarball, with retention, on a Diario / Semanal / Mensual schedule.
- **Ver estado** — the timer's status and next run (read-only).
- **Eliminar programación** — disable the timer and remove the units and script.

## Impact

- New spec: `scheduled-backups`.
- New code: `planners.plan_scheduled_backup` / `plan_remove_scheduled_backup` (+ script/unit builders, pure),
  `workflows/scheduled_backup.py` (`manage_scheduled_backup`), wired into `manage_existing_instance`.
- New planner tests; docs added. No new dependency (systemd + coreutils + `sudo -u postgres`).

## Scope

Local databases (via `sudo -u postgres pg_dump`, no stored password). Remote-DB scheduling is intentionally out
of scope to avoid persisting credentials in a unit; use the manual backup for remote databases.
