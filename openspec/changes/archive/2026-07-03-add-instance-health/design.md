# Design

Read-only, no plan/apply — like the audit report and the log-rotation query. `run_health_check(config)` reads
the instance conf and renders a tagged table.

## Probes

- **HTTP** (`_http_probe`) — stdlib `urllib.request.urlopen` against `127.0.0.1:<http_port>` with a 5s timeout,
  trying `/web/health` then `/web/login` then `/`. A 2xx/3xx (or a 4xx that still means "the server answered")
  counts as responsive; connection errors fall through to "sin respuesta". No `curl` dependency.
- **DB** (`_db_probe`) — `PGPASSWORD=<conf pw> psql -h … -tAc 'SELECT 1'` with the instance's own config
  credentials; exit 0 = reachable.
- **Disk** (`_disk_row`) — `df -Ph <path> | tail -1`, parsing the avail/use% columns; ≥ 90% used flags the row
  as a problem. Checked for the instance home and the resolved data dir.

## Testability

The subprocess/HTTP calls go through module-level names (`health.run`, `health.urllib.request.urlopen`,
`health.path_exists`) so tests patch them directly: `_http_probe` (numeric-port guard, 2xx healthy, no-response
unhealthy) and `_disk_row` (≥90% flagged, normal OK, missing path INFO).

## Out of scope

Historical/trend health, alerting, and remediation — the check is a point-in-time read-only snapshot; fixing a
problem (start the service, free disk) stays with the existing menus.
