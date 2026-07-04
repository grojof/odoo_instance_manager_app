# Tasks

## 1. Spec deltas

- [x] 1.1 data-backup-restore: MODIFIED "Duplication" (free the source: block/terminate/re-enable; safe name).
- [x] 1.2 `openspec validate duplicate-frees-source-connections --strict` passes.

## 2. Code

- [x] 2.1 `backup_restore.py`: `_is_safe_db_name(name)` guard (SQL-safe DB name).
- [x] 2.2 `backup_restore.py`: pure `_duplicate_db_command(host, port, user, password, source_db, target_db)`
      that blocks connections, terminates sessions, `createdb -T`, and re-enables via a `trap ... EXIT`.
- [x] 2.3 `_duplicate_instance`: validate source/target names, use the new command.
- [x] 2.4 i18n: Spanish entry for the new command description.

## 3. Docs & changelog

- [x] 3.1 `docs/operations/instance-management.md`: note that duplication no longer needs a manual stop.
- [x] 3.2 `CHANGELOG.md` `[Unreleased]` (Fixed).

## 4. Verify

- [x] 4.1 `openspec validate --strict`, `ruff`, `pytest`, `compileall` pass.
