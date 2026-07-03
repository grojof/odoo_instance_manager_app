# Tasks

## Phase 1 — housekeeping (PR 1)

- [x] 1.1 Remove dead `workflows._truncate_text`, `_list_odoo_conf_instances`, `_discover_odoo_conf_paths`.
- [x] 1.2 Remove dead `system.group_exists` and `system.print_status_line`; drop now-unused `ui.status_tag`
  and its import in `system.py`.
- [x] 1.3 Delete the duplicate `_sql_literal` / `_is_local_db_host` in `workflows.py`; import them from
  `planners.py`.
- [x] 1.4 Gate green (`ruff`, `pytest`, `openspec validate`, docs/provenance checks).

## Phase 2 — package skeleton (PR 2)

- [x] 2.1 Convert `workflows.py` into a `workflows/` package (`_core.py` holds the implementation; `__init__`
  re-exports the 8 entry functions); fix relative imports to the parent package; point test imports at
  `._core`.

## Phase 2b — common.py (PR 3)

- [x] 2.2 Move shared helpers into `workflows/common.py`; `_core` and later feature modules import from it.

## Phase 3 — report.py (PR 3)

- [x] 3.1 Extract the external-report cluster into `workflows/report.py`.
- [ ] 3.2 Replace the 27-field positional rows with an `InstanceReportRow` dataclass.

## Phase 4 — fail2ban.py + services.py (PR 4)

- [ ] 4.1 Extract `manage_fail2ban` + helpers into `workflows/fail2ban.py`.
- [ ] 4.2 Extract `manage_instance_services` into `workflows/services.py`.

## Phase 5 — backup_restore.py + purge.py (PR 5)

- [ ] 5.1 Extract backup/restore/duplicate into `workflows/backup_restore.py`.
- [ ] 5.2 Extract purge into `workflows/purge.py`; introduce a `DbAdminSession` dataclass.

## Phase 6 — install.py + manage.py (PR 6)

- [ ] 6.1 Extract install flows (+ port suggestion, cleanup) into `workflows/install.py`.
- [ ] 6.2 Extract manage flows into `workflows/manage.py`; leave `__init__` a thin re-export.
- [ ] 6.3 Consider enabling `E501` on the new modules.
