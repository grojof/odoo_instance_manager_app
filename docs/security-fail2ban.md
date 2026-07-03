---
type: how-to
title: "Fail2ban protection"
description: "Install a secure base, protect Odoo instances per jail, verify real client IPs, and operate bans."
tags: [security, fail2ban, hardening]
audience: [operator]
updated: 2026-07-03
---

# Fail2ban protection

The **Seguridad Fail2ban** menu installs and operates Fail2ban for the host and for individual Odoo
instances. The status header shows service/enabled state and tolerates a socket that has not yet come up
(reported as *waiting*, not an error).

## Secure base setup

**Instalar/config base segura** installs Fail2ban and writes a base configuration with `ufw` as the ban
action, enabling `sshd`, `nginx-http-auth`, `nginx-botsearch`, and `recidive`. You supply extra admin
IPs/networks to ignore (loopback is always ignored) and tune `bantime`, `findtime`, `maxretry`, and the
recidive bantime. The plan validates with `fail2ban-client -t`, enables/restarts the service, and waits for
the socket to be ready.

## Per-instance Odoo jail

**Activar protección Odoo por instancia** installs the shared `odoo-auth` filter and writes a dedicated
`odoo-auth-<instance>` jail bound to the instance log. Before activating, it **tests the filter** against the
log with `fail2ban-regex`.

### Real-client-IP check (important behind a proxy)

Odoo sits behind Nginx, so its log may record the **proxy/gateway** IP instead of the real client. Banning
those would lock out your own infrastructure. The tool assesses the last lines of the log:

- **Public IPs present** → reported OK; activation proceeds.
- **Only private/loopback IPs** → warns of the risk and **requires explicit confirmation** before enabling the
  jail. Recommendation: fix forwarded headers (`proxy_mode`, `X-Forwarded-For`) so Odoo logs the real client
  IP first.

Run this check on its own with **Verificar IP real en log Odoo**.

## Operating bans

- **Ver estado y jails** / **Ver detalle de jail** — inspect the current jails and a jail's detail.
- **Desbanear IP de jail** — lists the currently banned IPs for a jail (or accept a manual IP) and runs
  `fail2ban-client set <jail> unbanip <ip>`.
- **Probar regex Odoo** — ensures the default `odoo-auth` filter exists, validates the log and filter files,
  and runs `fail2ban-regex`.

## Related

- [Instance management](instance-management.md)
- [Fail2ban spec](../openspec/specs/fail2ban-protection/spec.md) — the full behavior contract.
