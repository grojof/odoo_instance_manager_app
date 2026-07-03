# Add UFW firewall management

## Why

Fail2ban is configured with `banaction = ufw`, but the tool never installed or configured UFW — it only warned
that bans wouldn't take effect without it. There was also no way to set a basic firewall for an Odoo server
(deny incoming, allow SSH/HTTP/HTTPS, allow PostgreSQL from the app server). This closes that gap.

## What changes

A new top-level **Firewall (UFW)** menu:

- **Ver estado** — `ufw status verbose` (read-only, shown on entry).
- **Instalar/config base segura** — install UFW if missing; default deny incoming / allow outgoing; allow the
  SSH port (before enabling, to avoid lock-out); allow HTTP/HTTPS; optionally allow PostgreSQL (5432) from a
  single IP; enable UFW.
- **Permitir puerto** — `ufw allow <port>/<tcp|udp>`.
- **Eliminar regla (por número)** — list numbered rules and delete one.
- **Habilitar / Deshabilitar UFW**.

## Impact

- New spec: `firewall-ufw`.
- New code: `planners.plan_ufw_base_setup` / `plan_ufw_allow_port` / `plan_ufw_delete_rule` (pure),
  `workflows/firewall.py` (`manage_firewall`), a new main-menu entry.
- New planner tests; docs added. No new runtime dependency (UFW is a system package the plan installs).
