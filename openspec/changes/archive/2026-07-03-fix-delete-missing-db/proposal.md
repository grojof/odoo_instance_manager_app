# Handle deleting an instance whose database doesn't exist

## Why

Deleting an instance and choosing to drop a database that doesn't exist crashed the tool: `dropdb` failed,
`apply_commands` raised, and nothing above the flow caught it (only `KeyboardInterrupt`/`EOFError` were
handled), so the CLI exited with a traceback. More generally, **any** failing command in a non-install plan
crashed the session the same way.

## What changes

- **Delete flow:** before adding the `dropdb`, best-effort check whether the database exists with the given
  credentials. If not found (absent or unreachable), warn — "No se encontró la base de datos '<db>' …; se
  omite su eliminación." — and skip the drop, continuing with the rest of the removal. The `dropdb` also gains
  `--if-exists` as a belt.
- **General safety net:** the main menu's action dispatch now also catches `RuntimeError`, reporting the
  failure and returning to the menu instead of crashing — so a failing command in any flow (delete, backup,
  restore, duplicate, fail2ban, config update, log rotation) no longer kills the session.

## Impact

- Affected specs: `instance-removal` (skip a non-existent DB with a warning) and `execution-safety` (graceful
  recovery from a failed command).
- Affected code: `workflows/common.py` (`_database_exists`), `workflows/manage.py` (`_delete_instance`
  pre-check + `dropdb --if-exists`), `odoo_instance_manager.py` (menu-level `RuntimeError` handling).
- New unit tests for `_database_exists` (found / absent / connection failure / SQL-escaped name). No new
  dependency.
