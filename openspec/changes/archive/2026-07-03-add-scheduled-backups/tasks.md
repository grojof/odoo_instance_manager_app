# Tasks

- [x] 1.1 Add `plan_scheduled_backup` / `plan_remove_scheduled_backup` (+ script/service/timer builders, pure).
- [x] 1.2 Add `workflows/scheduled_backup.py` (`manage_scheduled_backup`: configure / status / remove).
- [x] 1.3 Wire "Backups programados" into `manage_existing_instance`.
- [x] 2.1 Add the `scheduled-backups` spec.
- [x] 2.2 Add planner tests.
- [x] 2.3 Add `docs/scheduled-backups.md`, linked from the README and instance-management page.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a VM: configure a daily schedule, run `systemctl start odoo-backup-<inst>.service`,
  and confirm a dump + (optional) filestore appear and retention prunes older ones.
