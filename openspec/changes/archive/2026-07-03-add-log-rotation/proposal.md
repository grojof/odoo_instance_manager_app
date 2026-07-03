# Add log-rotation capability

## Why

Each instance logs to `/var/log/odoo/<instance>.log`, and the generated `odoo.conf` sets `logrotate = True`
(Odoo's built-in, deprecated in recent versions). Operators have no way, from the tool, to set up a proper
**system** logrotate policy for the Odoo log or to inspect the current rotation state — so instance logs can
grow unbounded or be rotated inconsistently.

## What changes

A new **log-rotation** capability, reached from the instance-management menu ("Rotación de logs"), with two
operations:

- **Configure** — write `/etc/logrotate.d/odoo-<instance>` for the instance's Odoo log with an operator-chosen
  policy (frequency daily/weekly/monthly, retention count, optional compression, optional size threshold),
  using `copytruncate` so the running service keeps writing without a restart. Ensures `logrotate` is
  installed and validates the config with `logrotate -d`. If the `odoo.conf` still has `logrotate = True`, it
  offers to set it to `False` to avoid rotating the same file twice.
- **Query** — show the instance's Odoo log path, whether a system logrotate policy exists (and its contents),
  a `logrotate -d` dry-run preview, the current log file sizes, and the state of Odoo's built-in `logrotate`
  flag. It notes that per-instance **Nginx** logs are rotated by the distro's own `/etc/logrotate.d/nginx`.

## Scope decisions

- **System logrotate for the Odoo log only.** Nginx per-instance logs are already covered by the distribution
  `nginx` logrotate; managing them here would double-rotate, so the tool reports that state instead of
  duplicating it.
- **`copytruncate`** (not a postrotate service reload) — simplest and safe for a long-running service holding
  the file open; the small window of possibly-missed lines during the copy is an accepted trade-off.

## Impact

- New spec: `log-rotation`.
- New code: `planners.plan_logrotate_config` + `_logrotate_content`; `workflows/logrotate.py`
  (`manage_log_rotation`); a new `InstanceConfig.logrotate_config_file` path; one new action in
  `manage_existing_instance`. No third-party dependency (`logrotate` is a system package the plan installs if
  missing).
- New unit tests for the planner; docs updated.
