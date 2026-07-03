# Tasks

- [x] 1.1 Add `planners.plan_backup_retention` (keep N newest of each backup kind).
- [x] 1.2 Add `workflows/diskusage.py` (report + retention cleanup + submenu); wire into `manage_existing_instance`.
- [x] 2.1 Add the `disk-usage` spec.
- [x] 2.2 Add a `plan_backup_retention` test.
- [x] 2.3 Add `docs/disk-usage.md`, linked from the README and instance-management page.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a VM: view usage and prune backups keeping N, confirming only the oldest are removed.
