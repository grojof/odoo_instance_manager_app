# Tasks

## 1. Spec deltas

- [x] 1.1 execution-safety, instance-removal, data-backup-restore, scheduled-backups, disk-usage,
      instance-configuration deltas.
- [x] 1.2 `openspec validate harden-data-operations --strict` passes.

## 2. Code

- [x] 2.1 `models.py`: validators for version, branch, domain, DB host, IP and DB names; `host_cidr`.
- [x] 2.2 `prompts.ask_text(validate=…)`; install, update and replica prompts use it.
- [x] 2.3 `system.py`: probes quote their argument; `database_owner`; listing by owner or exact name.
- [x] 2.4 `planners.py`: backup names per database, exact prune, fail-closed private scheduled script,
      `UMask=0077`, quoted pg_hba rule with the right prefix length.
- [x] 2.5 Delete keeps the data dir and removes the timer; purge discovery, role, timer and jail.
- [x] 2.6 Duplication guards, template copy that blocks and reopens the source, `dropdb --force`.
- [x] 2.7 Manual backup private; restore moves the old filestore aside and chowns the data dir.
- [x] 2.8 i18n entries.

## 3. Verify

- [x] 3.1 Unit tests; `ruff`; `tools/verify_data_safety.py`.

## 4. Docs

- [x] 4.1 `docs/operations/instance-management.md`, `docs/operations/scheduled-backups.md`,
      `docs/operations/disk-usage.md`, `docs/glossary.md`, `CHANGELOG.md`, `CONTRIBUTING.md`.
