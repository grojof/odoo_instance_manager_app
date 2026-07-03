# Tasks

- [x] 1.1 Add `InstanceConfig.nginx_access_log` / `nginx_error_log` path properties.
- [x] 1.2 Add `planners._nginx_logrotate_content` (create + postrotate SIGUSR1 reopen) and an `include_nginx`
  parameter on `plan_logrotate_config`; keep the Odoo stanza on `copytruncate`.
- [x] 1.3 `workflows/logrotate.py`: add `_nginx_logs_covered_by_system`; Configure detects coverage and offers
  to include Nginx logs when uncovered; Query reports Nginx rotation coverage (distro / this policy / neither).
- [x] 2.1 `log-rotation` spec: add the uncovered-Nginx requirement; update the query requirement.
- [x] 2.2 Add planner tests for the Nginx stanza and `include_nginx`.
- [x] 2.3 Update `docs/log-rotation.md`.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a disposable VM whose `nginx` logrotate does not cover `/var/log/nginx/*.log`: include
  the Nginx logs and confirm the `postrotate` reopen stanza is written and validates with `logrotate -d`.
