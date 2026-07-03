# Tasks

- [x] 1.1 Add `workflows/health.py`: `run_health_check` + `_http_probe` (urllib), `_db_probe` (psql),
  `_disk_row` (df, ≥90% flagged).
- [x] 1.2 Wire "Comprobar salud (health check)" into `manage_existing_instance`.
- [x] 2.1 Add the `instance-health` spec.
- [x] 2.2 Add `tests/test_health.py` (HTTP probe + disk classification).
- [x] 2.3 Add `docs/health-check.md`, linked from the README and instance-management page.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a VM: run the health check against a running and a stopped instance and confirm the
  probes report correctly.
