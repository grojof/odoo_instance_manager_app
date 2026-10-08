# Tasks

## 1. Spec deltas

- [x] 1.1 execution-safety, instance-provisioning, instance-removal, data-backup-restore, disk-usage,
      scheduled-backups, log-rotation.
- [x] 1.2 `openspec validate --specs` passes.

## 2. Code

- [x] 2.1 `models.py`: reserved instance names; `system.db_role_absent`.
- [x] 2.2 Install: free-name check at the prompt; confirm outside the try; previewed, asked cleanup of what the
      run made; database-only cleanup drops the new role only.
- [x] 2.3 Purge: owner/name selection, administrator roles refused, order, per-filestore removal on a shared
      data dir, role condition, guarded `userdel`, logrotate policy.
- [x] 2.4 `/var/log/odoo` root-owned, per-instance logs, `su` dropped from logrotate.
- [x] 2.5 Delete: owner check, order, data dir from both config locations, best-effort nginx, logrotate policy.
- [x] 2.6 Copies: scoped chown, move aside, copy into the target, source check, `REPLACE <target>`.
- [x] 2.7 Backup directory validation; retention by name; valid database names from file names.
- [x] 2.8 i18n entries.

## 3. Verification

- [x] 3.1 Unit tests (`tests/test_destructive_guards.py`).
- [x] 3.2 `tools/verify_data_safety.py` executes the copy, retention, log directory, install cleanup, purge
      account removal, delete without nginx, and the superuser refusal against a PostgreSQL of its own.
