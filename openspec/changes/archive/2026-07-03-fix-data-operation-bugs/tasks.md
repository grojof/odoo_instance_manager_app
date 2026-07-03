# Tasks

## 1. Backup atomicity and timestamps

- [x] 1.1 `_backup_instance`: one Python-computed timestamp for the whole operation; dump/tar to a `.partial`
  and `mv` on success (clean up + fail otherwise); `pg_dump -f` instead of `>` redirection.
- [x] 1.2 `update_existing_configs`: one timestamped backup directory shared by all config backup commands;
  report the actual destination path.

## 2. Robust psql listing

- [x] 2.1 Add `psql_flags` parameter to `_db_admin_psql_command`; `_list_instance_databases` passes `-tA`
  explicitly, removing the fragile `.replace("-c", ...)`.

## 3. Duplication filestore location

- [x] 3.1 `_duplicate_instance`: resolve the target filestore from `target_config` (target instance), not the
  source `config`.

## 4. Interruption safety

- [x] 4.1 `_execute_install_with_cleanup`: catch `KeyboardInterrupt` as well as `RuntimeError`, run cleanup,
  and return to the menu instead of re-raising.
- [x] 4.2 `main()`: handle `KeyboardInterrupt`/`EOFError` at the menu prompt (clean exit) and during an action
  (return to menu).

## 5. Path-component safety

- [x] 5.1 Add `_is_safe_path_component`; gate operator-entered DB names in `_backup_instance`,
  `_restore_backup`, and `_delete_instance` before building filestore paths.

## 6. ask_bool

- [x] 6.1 Accept `sí`/`s`/`y`/`yes` and `no`/`n`; re-prompt on unrecognized input; Enter → default.

## 7. Tests

- [x] 7.1 `tests/test_workflow_helpers.py`: `_is_safe_path_component` and `_db_admin_psql_command` flags
  (incl. a password containing `-c`).
- [x] 7.2 `tests/test_prompts.py`: `ask_bool` accepts `sí`, re-prompts, and honors the default.

## 8. Verify

- [x] 8.1 `ruff check`, `pytest`, `openspec validate --specs` pass locally.
- [ ] 8.2 (operator) On a disposable VM: confirm a DB+Filestore backup produces a matched pair, a failed dump
  leaves no `.dump`, a duplicated instance has its filestore, and Ctrl+C during an install cleans up and
  returns to the menu.
