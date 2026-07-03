---
type: how-to
title: "Auditing a server (external report)"
description: "Generate a read-only report of a server's Odoo instances, TLS posture, and versions."
tags: [audit, discovery, tls, reporting]
audience: [operator]
updated: 2026-07-03
---

# Auditing a server (external report)

**Informe para servidor externo** produces a **strictly read-only** report of an Ubuntu host running Odoo. It
discovers instances and inspects their state without building or applying any mutating plan — safe to run on a
server you are auditing or preparing to hand off.

## What it reports

- **System overview** — hostname, OS, kernel, architecture, virtualization, uptime, IPs, and the
  versions/paths of Python, the PostgreSQL client, and Nginx, plus the run/boot state of the PostgreSQL and
  Nginx services and a read-only `nginx -t` config probe. Missing probes show a "not detected" marker.
- **Per-instance detail** — discovered by cross-referencing:
  - systemd units whose content references Odoo (`odoo-bin` / `Description=Odoo`),
  - valid Odoo config files (must not be backup-like and must carry at least two expected Odoo keys),
  - Odoo-related Nginx vhosts,
  - filestore roots (excluding backup-like and `.ssh` paths).

  Each instance's home, config, and Python are derived from the service `ExecStart` when possible.
- **TLS posture** — classifies each instance's certificate (self-signed / Let's Encrypt / custom / incomplete
  / none) and reports certificate metadata and expiry status (OK / WARN if expiring within the threshold /
  MISSING / ERROR).
- **Odoo version** — read from `<home>/odoo/odoo/release.py` (`version_info`) when available.

Instance discovery also recognizes the legacy config path `/etc/<instance>/odoo.conf` in addition to the
default `/etc/odoo/<instance>/<instance>.conf`.

## Read-only guarantee

The audit is read-only with respect to **server configuration**: it never produces or applies an install,
configuration, or deletion command — see the
[read-only requirement in the spec](../openspec/specs/server-audit/spec.md).

Two operator-initiated extras are the only things it may write or actively probe, both harmless:

- **Export the report** — when you opt in, it writes a single report file to the path you choose (default under
  `./reports/`, relative to where you launched the tool as root). This is the only file the audit creates.
- **Active TLS checks** — when you opt in with an expiry threshold, it runs read-only `openssl` certificate
  checks; no certificate or service is modified.

## Related

- [Instance management](instance-management.md)
- [Configuration reference](configuration-reference.md)
