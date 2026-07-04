# Tasks

## 1. Spec deltas

- [x] 1.1 instance-configuration: MODIFIED "Instance discovery and selection" (listing scoped to instance role).
- [x] 1.2 instance-removal: MODIFIED "Total superuser purge" (discover DBs by owner + prefix; prompt DB user).
- [x] 1.3 `openspec validate scope-db-listing-by-owner --strict` passes.

## 2. Code

- [x] 2.1 `system.py`: `list_databases(..., owner="")` — role-owned or name-prefixed filter (sanitized).
- [x] 2.2 `common.py`: `_probe_databases_for_management` and `_pick_db_name` scope by the connected role.
- [x] 2.3 `purge.py`: prompt for the instance DB user; `_list_instance_databases` matches prefix **or** owner.
- [x] 2.4 i18n: Spanish entries for the new prompt(s).

## 3. Docs & changelog

- [x] 3.1 `docs/operations/instance-management.md`: note the scoped DB listing.
- [x] 3.2 `CHANGELOG.md` `[Unreleased]`.

## 4. Verify

- [x] 4.1 `openspec validate --strict`, `ruff`, `pytest`, `compileall` pass.
