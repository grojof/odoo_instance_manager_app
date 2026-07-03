# Tasks

- [x] 1.1 Remove `logrotate = True` from `planners._odoo_conf_content`.
- [x] 1.2 Rename `plan_logrotate_config`'s `disable_odoo_internal` → `remove_obsolete_odoo_key` and make it
  delete the stale `logrotate` line.
- [x] 2.1 Query: report Odoo log rotation as ACTIVA/INACTIVA; note a stale `logrotate` conf key when present.
- [x] 2.2 Configure: offer to remove the stale `logrotate` key when present (instead of "disable internal").
- [x] 3.1 Install: add `_maybe_plan_logrotate` (default yes) and wire it into `install_odoo_only` /
  `install_odoo_and_db`.
- [x] 4.1 Specs: `log-rotation` (obsolete-key cleanup + active/inactive query) and `instance-provisioning`
  (optional install-time rotation).
- [x] 4.2 Tests: `odoo.conf` has no `logrotate`; `remove_obsolete_odoo_key` deletes the key.
- [x] 4.3 Docs: update `docs/configuration-reference.md` and `docs/log-rotation.md`.
- [x] 5.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 5.2 (operator) On a VM: install an instance with rotation enabled and confirm the policy file exists;
  query an instance and confirm the ACTIVA/INACTIVA status.
