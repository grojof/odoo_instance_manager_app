# Add instance health check

## Why

The status view lists which resources *exist*, but not whether the instance is actually **working**. Operators
need a quick, read-only "is it healthy?" that catches the common production problems: the service is down, it's
up but not answering HTTP, the database is unreachable, or the disk is full.

## What changes

A new read-only **instance-health** capability, from *Gestionar instancias → Comprobar salud (health check)*,
that probes and reports (each tagged healthy / problem):

- **Service** — systemd active state + autostart.
- **HTTP** — a local GET to the instance's HTTP port (`/web/health`, falling back to `/web/login` and `/`);
  any 2xx/3xx means it answers. Uses stdlib `urllib` (no `curl` dependency).
- **Database** — a `psql SELECT 1` with the instance's own config credentials.
- **Disk** — free space and usage on the instance home and data directory, flagged when a filesystem is ≥ 90%.

## Impact

- New spec: `instance-health`.
- New code: `workflows/health.py` (`run_health_check` + `_http_probe` / `_db_probe` / `_disk_row`), wired into
  `manage_existing_instance`.
- New unit tests for the HTTP probe and disk-usage classification. stdlib only — no new dependency.
