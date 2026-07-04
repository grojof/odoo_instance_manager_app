# Scope database listings to the instance's DB user

## Why

When managing an instance (and in the total-purge flow), listing databases shows **every** database on the
server, which is confusing and unhelpful — you only care about the ones belonging to this instance. Now that
each instance's databases are isolated to their owning role, the natural scope is the **instance's DB user**:
list only the databases owned by that role (or named after the instance).

## What changes

- **instance-configuration — Optional database listing (MODIFIED):** the management database listing SHALL be
  **scoped to the connected instance role** — only databases owned by that role (or whose name starts with it)
  are listed, instead of all databases on the server.
- **instance-removal — Database discovery (MODIFIED):** the total-purge flow SHALL ask for the instance's DB
  user and discover the instance's databases by **owner** as well as by name prefix, so all databases
  associated with the instance are found and cleaned.
- Enabling change: `list_databases(...)` gains an optional `owner` filter (role-owned or name-prefixed),
  reused by the management probe, the DB picker, and the purge discovery.

## Impact

- Specs: `instance-configuration`, `instance-removal`.
- Code: `system.py` (`list_databases(owner=...)`), `workflows/common.py` (probe + picker),
  `workflows/purge.py` (owner-aware discovery + DB-user prompt).
- Docs: `docs/operations/instance-management.md`; `CHANGELOG.md` `[Unreleased]`.
- Tests: `tests/test_system.py` / `tests/test_db_existence.py` as applicable (owner-filter SQL).

## Note

Stacked on the manage-menu-submenus change.
