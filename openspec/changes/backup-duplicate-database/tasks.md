# Tasks

## 1. Spec deltas

- [x] 1.1 data-backup-restore: ADDED "Standalone database duplication".
- [x] 1.2 `openspec validate backup-duplicate-database --strict` passes.

## 2. Code

- [x] 2.1 `backup_restore.py`: `_duplicate_database(config, cached)` — local-only DB duplication reusing
      `_seed_db_commands` / `_drop_db_commands` (overwrite) / `_post_db_mode_commands` /
      `_filestore_copy_commands`; method + copied/moved + neutralize + optional filestore; phrase confirm.
- [x] 2.2 `manage.py`: add a "Duplicate database" action.
- [x] 2.3 i18n: Spanish entries for the new prompts/labels.

## 3. Docs & changelog

- [x] 3.1 `docs/operations/instance-management.md`: document Duplicate database.
- [x] 3.2 `CHANGELOG.md` `[Unreleased]`.

## 4. Verify

- [x] 4.1 `openspec validate --strict`, `ruff`, `pytest`, `compileall` pass.
