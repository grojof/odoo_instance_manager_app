# Design

## Method per service (the "modern best practice" answer)

Log rotation for a running service depends on whether the service can **reopen** its log on a signal:

- **Nginx can** (SIGUSR1 reopens the access/error logs). The idiomatic, distribution-standard method — and the
  one Ubuntu 24.04's own `/etc/logrotate.d/nginx` uses — is `create` + a `postrotate` `kill -USR1`. This
  rotates cleanly with no lost lines, so it is preferred over `copytruncate`.
- **Odoo cannot** (no log-reopen signal). For a system logrotate policy the practical method is
  `copytruncate` (copy then truncate the open file); the tiny copy-window is the accepted trade-off. So the
  Odoo stanza keeps `copytruncate`.

Using the correct method per service *is* the best practice — not a single method for both.

## Coverage detection

`workflows/logrotate._nginx_logs_covered_by_system()` reads `/etc/logrotate.d/nginx` and treats the instance's
Nginx logs as covered when it contains the standard `/var/log/nginx/*.log` (or `/var/log/nginx/*`) glob — which
matches `<instance>.access.log` / `<instance>.error.log`. This keeps the tool from adding a second policy for
files the distro already rotates (double rotation).

Detection is I/O, so it lives in the workflow (planners stay pure); the workflow passes `include_nginx` to
`plan_logrotate_config`.

## Nginx stanza

```
/var/log/nginx/<instance>.access.log /var/log/nginx/<instance>.error.log {
    <frequency>
    rotate <count>
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    compress / delaycompress      # when compression is on
    postrotate
        [ -f /run/nginx.pid ] && kill -USR1 "$(cat /run/nginx.pid)"
    endscript
}
```

`sharedscripts` runs the `postrotate` once even though two files are listed. `/run/nginx.pid` is the modern
path on 24.04 (`/var/run` is a symlink to `/run`). Both the Odoo and (optional) Nginx stanzas live in the same
`/etc/logrotate.d/odoo-<instance>` file so the instance's rotation is one place to read and manage.

## Query

Query now classifies Nginx coverage three ways: rotated by the distro (`_nginx_logs_covered_by_system()`
true), rotated by this tool's policy (the instance's Nginx access-log path appears in the policy file), or
neither (a warning to configure it).

## Testing

Pure-planner tests cover the Nginx stanza (paths, `create`, `sharedscripts`, `postrotate` `kill -USR1`, no
`copytruncate`) and that `include_nginx` toggles the stanza while the Odoo stanza keeps `copytruncate`. The
interactive detection/prompt is covered by operator acceptance.
