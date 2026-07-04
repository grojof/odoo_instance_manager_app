---
type: reference
title: "What the utility offers & supported platforms"
description: "Capability overview and the OS / nginx / PostgreSQL / Odoo support matrix, plus what is out of scope."
tags: [reference, platforms, support, capabilities]
audience: [operator, contributor]
updated: 2026-07-04
---

# What the utility offers & supported platforms

## What it offers

An interactive, root-run CLI that provisions and maintains multiple **Odoo Community** instances on one
server, always through a previewed **plan → confirm → apply** flow. Capabilities:

| Area | What you get |
|------|--------------|
| Provisioning | Odoo-only, PostgreSQL-only, or both; isolated system user + venv per instance; systemd unit; Nginx (HTTP/HTTPS); TLS (self-signed / your certs / external Let's Encrypt). |
| Secure defaults | Strong random master/DB passwords, `list_db = False`, a `dbfilter`, and `db_sslmode = require` for remote databases — each recommended but an **informed, warned choice**. |
| Reports (PDF) | Optional **wkhtmltopdf** install: the checksum-verified Qt-patched 0.12.6 build, a distro fallback, or skip. |
| Performance | `workers`/memory limits derived from the host's CPU and RAM, with operator override. |
| Security | Fail2ban jails (SSH, Nginx, per-instance Odoo), a UFW firewall baseline, TLS management. |
| Operations | Health check, disk usage & retention, log rotation, addon inventory, manual and scheduled backups, restore, duplicate. |
| Audit | A read-only whole-server report, including a per-instance **production-posture** summary. |

## Version-adaptive configuration

The tool detects the version-sensitive components and renders configuration that matches them, instead of
assuming a single stack:

| Detected | Probe | What adapts |
|----------|-------|-------------|
| OS codename | `/etc/os-release` | wkhtmltopdf asset selection; unsupported-family warning |
| nginx version | `nginx -v` | `listen … ssl http2` (nginx < 1.25.1) vs `http2 on;` (≥ 1.25.1) |
| Odoo major | provided at install | `gevent_port` (≥ 16) vs `longpolling_port` (≤ 15); Nginx `/websocket` vs `/longpolling/poll` |
| PostgreSQL version | `SHOW server_version` | `scram-sha-256` support check (audit signal) |
| CPU / RAM | `nproc`, `/proc/meminfo` | derived `workers` and memory limits |

## Support matrix

| Component | Supported | Notes |
|-----------|-----------|-------|
| OS family | Debian/Ubuntu (**apt**) | Package steps target apt. A non-apt OS is detected and warned, not driven blindly. |
| Ubuntu | 22.04 (jammy), 24.04 (noble) | Validated primary targets. Newer releases work; the wkhtmltopdf table maps noble → the jammy build. |
| Debian | 11 (bullseye), 12 (bookworm) | wkhtmltopdf assets pinned for both. |
| nginx | 1.18 → 1.25+ | HTTP/2 directive form chosen by detected version; `nginx -t` passes on either. |
| PostgreSQL | 10+ | `scram-sha-256` requires ≥ 10 (every supported Ubuntu/Debian ships newer). |
| Odoo Community | 15 → 18 (and newer) | Live-chat/bus key and Nginx location adapt to the major. |
| wkhtmltopdf | 0.12.6.1-3 (patched) | jammy/noble, bookworm, bullseye assets, each SHA-256-pinned; other codenames use the distro package or skip. |

## Out of scope

- **PostgreSQL performance tuning** of `postgresql.conf` (shared_buffers, work_mem, …) — a separate concern.
- **Non-apt OS families** (RHEL/Alma/Arch) for package installation.
- **Enterprise** Odoo and managed/SaaS hosting.
- Offsite/remote backup destinations (backups are written locally).

## Related

- [Configuration reference](configuration-reference.md) — every field and derived path.
- [Installing and provisioning instances](installation.md) — the install flow and prompts.
- [Auditing a server](server-audit.md) — the read-only report and posture summary.
