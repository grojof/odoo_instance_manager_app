# Group the instance-management menu into submenus

## Why

The "Manage instances" menu had grown to ~18 flat entries (four status views, health, configuration, four
backup/duplication actions, delete, …), which is hard to scan. Grouping keeps the top menu short and the
actions discoverable.

## What changes

- **instance-configuration — Management menu grouping (ADDED):** the management menu SHALL present grouped
  submenus — **Status & health**, **Configuration**, **Backups & duplication** — plus a top-level **Delete
  instance**, each opening a submenu of its actions. Behavior of the actions is unchanged.

## Impact

- Spec: `instance-configuration`.
- Code: `manage.py` — two-level menu in `manage_existing_instance` (same handlers).
- Docs: `docs/operations/instance-management.md`; `CHANGELOG.md` `[Unreleased]`.

## Note

Stacked on the backup-duplicate-database change (its "Duplicate database" action lives under the new
"Backups & duplication" submenu).
