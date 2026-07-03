# Design

## Two layers of protection

1. **Avoid the failure (good UX).** `_delete_instance` checks database existence before building the drop
   command. `common._database_exists(creds, db_name)` runs
   `psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname=<escaped>"` with the operator's credentials
   and returns `True` only on `rc == 0` and output `1`. A non-existent **or** unreachable database returns
   `False`, so the tool warns and skips the drop (and continues removing the service/config/files). The
   `db_name` is SQL-escaped (single quotes doubled) and the whole SQL is shell-quoted — no injection, no crash.
   The emitted `dropdb` gains `--if-exists` as defense in depth (covers a race between the check and apply).

2. **Survive any failure (safety net).** The root cause was broader than `dropdb`: every non-install flow
   calls `_execute_plan` → `apply_commands`, which raises `RuntimeError` on a failed command, and `main()`'s
   dispatch only caught `KeyboardInterrupt`/`EOFError`. It now also catches `RuntimeError`, prints the reported
   failure, and returns to the menu. Installs keep their existing cleanup-then-return behavior
   (`_execute_install_with_cleanup`).

## Why best-effort (False on connection error)

Treating "couldn't verify" the same as "doesn't exist" is the safe choice for a *delete*: skipping the drop
never loses data, whereas attempting it on an unreachable host would fail. The warning is worded to cover both
("no existe o no se pudo conectar"), so the operator can retry with correct credentials if needed.

## Testing

`tests/test_db_existence.py` drives `_database_exists` through a fake `run` seam: `1` → True, empty → False,
non-zero return → False, and a name containing `'` is doubled in the SQL literal. The interactive delete flow
and the menu-level recovery are covered by operator acceptance.
