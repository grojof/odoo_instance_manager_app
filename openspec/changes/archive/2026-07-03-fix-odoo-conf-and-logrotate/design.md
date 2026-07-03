# Design

## odoo.conf options review

`_odoo_conf_content` was audited against modern Odoo (17/18):

- **Removed:** `logrotate = True` — Odoo dropped its built-in log rotation in v13; the key is ignored, so
  emitting it is misleading. System logrotate (this capability) is the supported path.
- **Kept (all current):** `admin_passwd`, `list_db`, `addons_path`, `http_interface`, `http_port`,
  `gevent_port` (the modern replacement for `longpolling_port`), `proxy_mode`, `logfile`, `workers`,
  `max_cron_threads`, the `limit_*` tuning keys, and the `db_*` connection keys.

## Obsolete-key cleanup (replacing the "disable built-in" step)

Because there is no built-in rotation to disable, `plan_logrotate_config`'s `disable_odoo_internal`
(flipping `logrotate = True` → `False`) is replaced by `remove_obsolete_odoo_key`, which **deletes** any
`logrotate` line from the conf (`sed -ri '/^\s*logrotate\s*=/d'`). Configure offers it only when the key is
present; removing an already-ignored key needs no service restart.

## Active/inactive status

Query computes `odoo_active = policy_file_exists AND /var/log/odoo/<instance>.log ∈ policy_content` and shows a
tagged row (**ACTIVA (system logrotate)** / **INACTIVA**) at the top of the status table, so the operator sees
the answer immediately rather than inferring it from the policy dump.

## Install-time rotation

`workflows/install._maybe_plan_logrotate(config)` mirrors `_maybe_plan_certs`: it asks "¿Configurar rotación de
logs de la instancia (recomendado)?" (default **yes**) and, when accepted, appends
`plan_logrotate_config(config, frequency="weekly", rotate_count=14, compress=True)` to the install plan. It is
wired into `install_odoo_only` and `install_odoo_and_db` (not `install_db_only`, which installs no Odoo log).
Nginx logs are left to the distro at install time (the query/Configure flow handles the uncovered case later).

## Testing

Pure-planner tests: the generated `odoo.conf` no longer contains `logrotate` and still carries the current keys;
`plan_logrotate_config(remove_obsolete_odoo_key=...)` adds the delete-`sed` only when requested. The
interactive install prompt and query status are covered by operator acceptance.
