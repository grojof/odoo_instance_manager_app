---
type: how-to
title: "Instance health check"
description: "A read-only check of an instance: service, HTTP, database, and disk."
tags: [health, monitoring, maintenance]
audience: [operator]
updated: 2026-07-03
---

# Instance health check

From **Gestionar instancias → Comprobar salud (health check)**, the tool runs a **read-only** check and reports
whether the instance is actually working — not just whether its files exist.

## What it checks

| Check | Healthy when | How |
|-------|--------------|-----|
| **Servicio Odoo** | the systemd service is active | `systemctl is-active` (+ autostart state) |
| **HTTP local** | the instance answers on its HTTP port | stdlib `urllib` GET to `127.0.0.1:<http_port>` (`/web/health` → `/web/login` → `/`); any 2xx/3xx counts |
| **Conexión DB** | the database is reachable | `psql SELECT 1` with the instance's own config credentials |
| **Disco (home / data dir)** | the filesystem is below 90% used | `df -Ph`; ≥ 90% is flagged |

Each row is tagged healthy or a problem. If the service is active but HTTP does not answer, the check warns to
look at the Odoo log; if the service is down, it points you to *Servicios instancias*.

It changes nothing — it only runs inspection commands and one local HTTP GET (no `curl` dependency, stdlib
only).

## Related

- [Managing existing instances](instance-management.md)
- [Server audit](../server-audit.md) — the whole-server read-only report.
