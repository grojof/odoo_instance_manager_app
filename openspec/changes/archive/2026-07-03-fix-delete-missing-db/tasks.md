# Tasks

- [x] 1.1 Add `common._database_exists(creds, db_name)` (best-effort, SQL-escaped, False on absence/failure).
- [x] 1.2 `_delete_instance`: pre-check the DB and warn+skip when not found; add `--if-exists` to the `dropdb`.
- [x] 2.1 `main()`: catch `RuntimeError` in the action dispatch and return to the menu.
- [x] 3.1 Specs: `instance-removal` (skip non-existent DB) and `execution-safety` (graceful recovery).
- [x] 3.2 Add `tests/test_db_existence.py`.
- [x] 4.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 4.2 (operator) On a VM: delete an instance choosing to drop a non-existent DB and confirm it warns,
  skips the drop, and finishes the rest without crashing.
