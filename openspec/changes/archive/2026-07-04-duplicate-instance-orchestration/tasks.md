# Tasks

## 1. Spec deltas

- [x] 1.1 data-backup-restore: MODIFIED "Duplication" (replica/refresh orchestration + selectable copy method).
- [x] 1.2 `openspec validate duplicate-instance-orchestration --strict` passes.

## 2. Code — enabling change

- [x] 2.1 `planners.py`: `plan_odoo_base_setup(..., start_now=True)` — provision without starting when False
      (enable/disable autostart, but only start when `start_now`).

## 3. Code — DB seed helpers (shared, pure)

- [x] 3.1 `backup_restore.py`: `_seed_db_commands(creds, source_db, target_db, method)` — `method="template"`
      reuses the free-source template copy; `method="dump"` = `createdb` + `pg_dump | pg_restore --no-owner`.
- [x] 3.2 `backup_restore.py`: `_drop_db_commands(creds, db_name)` — terminate connections + `dropdb --if-exists`
      (for the refresh path).

## 4. Code — orchestration

- [x] 4.1 `_duplicate_instance`: detect whether the target exists; pick copy method; copied/moved + neutralize.
- [x] 4.2 Replica path: ensure target role, base setup (`start_now=False`) with detected source version,
      suggested ports, generated secrets, optional Nginx; seed DB + filestore; start service.
- [x] 4.3 Refresh path: stop target service, drop+seed DB, replace filestore, neutralize, start service.
- [x] 4.4 i18n: Spanish entries for new prompts/labels.

## 5. Docs & changelog

- [x] 5.1 `docs/operations/instance-management.md`: duplication now provisions (replica) or refreshes.
- [x] 5.2 `CHANGELOG.md` `[Unreleased]`.

## 6. Verify

- [x] 6.1 `openspec validate --strict`, `ruff`, `pytest`, `compileall` pass; generated seed scripts pass `bash -n`.
