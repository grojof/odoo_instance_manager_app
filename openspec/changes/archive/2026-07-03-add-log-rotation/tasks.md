# Tasks

## 1. Model + planner

- [x] 1.1 Add `InstanceConfig.logrotate_config_file` (`/etc/logrotate.d/odoo-<instance>`).
- [x] 1.2 Add `planners._logrotate_content` and `planners.plan_logrotate_config` (install-if-missing, write,
  `logrotate -d` validation, optional `sed` to disable Odoo's built-in `logrotate`).

## 2. Workflow + menu

- [x] 2.1 Add `workflows/logrotate.py` with `manage_log_rotation` (Configure / Query submenu).
- [x] 2.2 Wire a "Rotación de logs" action into `manage_existing_instance`.

## 3. Spec + tests + docs

- [x] 3.1 Add the `log-rotation` capability spec (configure, avoid double rotation, query).
- [x] 3.2 Add `tests/test_planners.py` for `_logrotate_content` / `plan_logrotate_config`.
- [x] 3.3 Document the capability (new `docs/log-rotation.md`, linked from the README map and instance
  management page).

## 4. Verify

- [x] 4.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 4.2 (operator) On a disposable VM: configure rotation, run `logrotate -d`, and confirm the policy file
  and (if chosen) `logrotate = False` in the conf.
