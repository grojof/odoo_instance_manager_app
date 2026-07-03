# Fix odoo.conf options and default log rotation

## Why

Operator feedback surfaced three log-rotation / config issues:

1. The generated `odoo.conf` sets `logrotate = True`, an option **removed from Odoo in v13** — it is an ignored
   no-op and shouldn't be written.
2. The log-rotation **Query** shows the policy but never states plainly whether rotation of the instance's
   Odoo log is **active or not**.
3. Rotation isn't offered **at install time**, so a fresh instance starts with no rotation unless the operator
   remembers to configure it later.

## What changes

- **Remove `logrotate = True`** from the generated `odoo.conf`. Since Odoo has no built-in rotation any more,
  the previous "disable Odoo's built-in logrotate" step is replaced by an offer to **delete a stale
  `logrotate` key** from an existing conf (Configure), and the query notes when one is present.
- **Query reports active/inactive**: a clear "Rotación log Odoo: ACTIVA (system logrotate) / INACTIVA" line,
  based on whether a system logrotate policy covering the Odoo log exists.
- **Install-time rotation, default on**: the Odoo-installing flows offer to configure log rotation for the
  instance's Odoo log (recommended, defaults to yes).

## Impact

- Affected specs: `log-rotation` (obsolete-key cleanup replaces the built-in-logrotate requirement; query
  reports active/inactive) and `instance-provisioning` (optional install-time rotation).
- Affected code: `planners._odoo_conf_content` (drop `logrotate`); `plan_logrotate_config`
  (`disable_odoo_internal` → `remove_obsolete_odoo_key`, deletes the key); `workflows/logrotate.py` (query
  status + cleanup prompt); `workflows/install.py` (`_maybe_plan_logrotate`, wired into the Odoo installs).
- Docs and tests updated. No new runtime dependency.
