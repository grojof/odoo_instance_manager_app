# Extend log rotation to Nginx logs (when uncovered)

## Why

The initial `log-rotation` capability managed only the Odoo log and always deferred the instance's Nginx logs
to the distribution's `nginx` logrotate. On a standard Ubuntu that is correct (the distro rotates
`/var/log/nginx/*.log`), but on hosts where that coverage is absent the per-instance Nginx logs would grow
unbounded with no option to manage them from the tool.

## What changes

- **Detect** whether `/etc/logrotate.d/nginx` already covers `/var/log/nginx/*.log`. During Configure, if it
  does, the tool skips Nginx (reporting it, to avoid double rotation); if it does not, it offers to include the
  instance's Nginx logs.
- **Rotate Nginx logs with the modern, Nginx-idiomatic method** for Ubuntu 24.04+ — `create 0640 www-data adm`,
  `sharedscripts`, and a `postrotate` that reopens Nginx via `kill -USR1 $(cat /run/nginx.pid)` — matching the
  distribution's own approach. This is **not** `copytruncate`: Nginx reopens its logs on SIGUSR1, so
  `copytruncate`'s copy-window line loss is unnecessary and avoided.
- The **Odoo log keeps `copytruncate`** because Odoo has no log-reopen signal — the right method per service.
- **Query** now reports who rotates the Nginx logs: the distro, this tool's policy, or neither.

## Impact

- Affected spec: `log-rotation` (add a Nginx-coverage requirement; update the query requirement).
- Affected code: `models` (Nginx log path properties), `planners` (`_nginx_logrotate_content`; `include_nginx`
  on `plan_logrotate_config`), `workflows/logrotate.py` (coverage detection + prompt + query reporting).
- New unit tests for the Nginx stanza and `include_nginx`; docs updated.
- No new runtime dependency.
