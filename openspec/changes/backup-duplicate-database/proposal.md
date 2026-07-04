# Standalone "Duplicate database" backup action

## Why

The backup area has create / restore / scheduled backups, and full instance duplication. But a common need is
to just **duplicate a database** — with the same copied/moved + neutralize semantics — without provisioning or
touching an instance's service and config (e.g. a quick throwaway copy of the current instance's DB).

## What changes

- **data-backup-restore — Standalone database duplication (ADDED):** a database-only duplication that copies a
  source DB into a target on the **local** server, reusing the selectable copy method (template or
  `pg_dump | pg_restore --role`), the copied/moved and neutralize semantics, and an optional filestore copy
  under the **current instance's** data directory. It touches no instance service or config, validates names,
  requires phrase confirmation, and requires an explicit overwrite when the target DB already exists.
- A new **Duplicate database** action in the instance-management menu (grouped into submenus by the follow-up
  change).

## Impact

- Spec: `data-backup-restore`.
- Code: `backup_restore.py` — `_duplicate_database(config, cached)` reusing `_seed_db_commands`,
  `_drop_db_commands`, `_post_db_mode_commands`, `_filestore_copy_commands`, `_is_safe_db_name`; wired into
  `manage.py`.
- Docs: `docs/operations/instance-management.md`; `CHANGELOG.md` `[Unreleased]`.
- Tests: covered by the shared helpers (already tested in `tests/test_backup_restore.py`).

## Note

Stacked on the instance-duplication-orchestration change (reuses its DB seed helpers).
