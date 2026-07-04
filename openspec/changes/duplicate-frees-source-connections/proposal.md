# Duplication frees the source database of active sessions

## Why

Duplicating an instance fails whenever the **source** instance is running:

```
createdb: error: database creation failed: ERROR:  source database "odoo18test" is being accessed by other users
DETAIL:  There are 5 other sessions using the database.
```

PostgreSQL's `CREATE DATABASE … TEMPLATE` requires that **no other sessions** are connected to the template
database, but the source Odoo service keeps worker connections open. Today the operator must stop the source
service by hand — undocumented and easy to miss. This mirrors what Odoo's own database-manager "duplicate"
does: it terminates the source's sessions before the template copy.

## What changes

- **data-backup-restore — Duplication (MODIFIED):** the duplication plan prepares the source for the template
  copy — **blocks new connections**, **terminates existing sessions**, runs `createdb -T`, and **re-enables
  connections to the source afterward, even if the copy fails** (via a shell `trap`), so the operator need not
  stop the source service. Runs with the instance's own role (owner of its database); no superuser required.
- The source database name is validated as a safe name before it is interpolated into the SQL statements.

## Impact

- Spec: `data-backup-restore`.
- Code: `instance_manager/workflows/backup_restore.py` — a pure `_duplicate_db_command(...)` builder plus a
  `_is_safe_db_name(...)` guard; `_duplicate_instance` uses them. No new dependency.
- Docs: `docs/operations/instance-management.md`; `CHANGELOG.md` `[Unreleased]`.
- Tests: `tests/test_backup_restore.py` (command structure + name safety).

## Trade-off

The source instance is briefly disconnected during the copy (a short blip for anyone using it), exactly like
Odoo's own duplicate. The alternative — duplicating via `pg_dump | pg_restore` (no disconnect, slower) — is
noted as a possible future mode but is out of scope here.
