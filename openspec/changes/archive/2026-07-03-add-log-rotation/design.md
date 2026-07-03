# Design

## Layering

Follows the existing pattern: a **pure planner** builds the command list; a **workflow** collects input and
runs it through the standard preview → confirm → apply flow.

- `models.InstanceConfig.logrotate_config_file` → `/etc/logrotate.d/odoo-<instance>` (all instance paths derive
  from the config).
- `planners._logrotate_content(config, frequency, rotate_count, compress, maxsize)` → the logrotate stanza.
- `planners.plan_logrotate_config(config, *, frequency, rotate_count, compress, maxsize, disable_odoo_internal)`
  → ensure `logrotate` installed, write the file (mode 644), `logrotate -d` validation, and (optionally) a
  `sed` that flips `logrotate = True` → `False` in the `odoo.conf`.
- `workflows/logrotate.py::manage_log_rotation(config)` → a small Configure / Query / Volver menu, invoked from
  `manage_existing_instance`.

## logrotate stanza

```
/var/log/odoo/<instance>.log {
    <frequency>          # weekly | daily | monthly
    rotate <count>
    missingok
    notifempty
    copytruncate
    su <instance> <instance>
    compress             # when compression is on
    delaycompress        # when compression is on
    maxsize <size>       # when a size threshold is chosen
}
```

- **`copytruncate`** avoids needing to restart or signal Odoo — logrotate copies then truncates the file the
  service holds open.
- **`su <instance> <instance>`** — `/var/log/odoo` is owned by the instance user, so modern logrotate requires
  the `su` directive to rotate it safely.

## Double-rotation guard

The generated `odoo.conf` historically sets `logrotate = True` (Odoo's own rotator). Running that *and* system
logrotate on the same file double-rotates, so Configure detects the flag, warns, and offers to set
`logrotate = False` via a targeted `sed` (idempotent; guarded by `test -f`). The change needs an Odoo restart,
which the tool tells the operator to do from the services menu (it does not restart silently).

## Nginx logs are out of scope by design

The distribution's `/etc/logrotate.d/nginx` rotates `/var/log/nginx/*.log`, which already covers the
per-instance `<instance>.access.log` / `.error.log`. Adding a second policy for them would double-rotate, so
the capability manages only the Odoo log and *reports* that Nginx logs are handled by the system nginx
logrotate. (If per-instance Nginx rotation is later wanted, it would replace — not duplicate — the distro
policy, a separate change.)

## Testing

The planner is pure and unit-tested (`tests/test_planners.py`): stanza directives (frequency, retention,
`copytruncate`, `su`, compression on/off, `maxsize`), and the plan shape (install + write + `logrotate -d`, and
the `sed` present only when disabling the built-in). The interactive query/configure menus are covered by
operator acceptance on a real host.
