---
type: how-to
title: "Auditing a server (external report)"
description: "Generate a read-only report of a server's Odoo instances, TLS posture, and versions."
tags: [audit, discovery, tls, reporting]
audience: [operator]
updated: 2026-10-08
---

# Auditing a server (external report)

**External server report** produces a **strictly read-only** report of an Ubuntu host running Odoo. It
discovers instances and inspects their state without building or applying any mutating plan — safe to run on a
server you are auditing or preparing to hand off.

## What it reports

The report's sections, in the order it prints them:

- **Server summary** — hostname, OS, kernel, architecture, virtualization, uptime, IPs, and the versions and
  paths of Python, the PostgreSQL client, Nginx and **wkhtmltopdf**. It also gives the run and boot state of the
  PostgreSQL and Nginx services and a read-only `nginx -t` probe. A missing probe shows "not detected".
- **Detected Odoo services**, **Artifacts found by search**, **Detected Odoo configuration files**,
  **Odoo-related Nginx configs**, **Detected filestores** — what discovery cross-references:
  - systemd units whose content references Odoo (`odoo-bin` / `Description=Odoo`);
  - valid Odoo config files (not backup-like, with at least two expected Odoo keys);
  - Odoo-related Nginx vhosts;
  - filestore roots (excluding backup-like and `.ssh` paths).
- **Instances: Odoo / paths / DB**, **Instances: Python**, **Instances: Nginx / ports** — per instance:
  - home, config and paths, derived from the service's `ExecStart` when possible;
  - the Odoo version, read from `<home>/odoo/odoo/release.py`;
  - the venv's Python, read from its `pyvenv.cfg`, never by running the instance's interpreter as root;
  - the instance's databases, its vhosts and its ports.
- **Production posture** — a per-instance table of the checks listed under
  [security & production posture](operations/instance-management.md#security--production-posture), computed
  from each instance's `odoo.conf` plus host facts; read-only.
- **TLS certificate detail** — each instance's certificate mode (self-signed / Let's Encrypt / custom /
  incomplete / none) with its metadata and expiry (OK / WARN within the threshold / MISSING / ERROR).
- **Active TLS checks** — only when you opt in: read-only `openssl` checks with an expiry threshold.

Instance discovery also recognizes the legacy config path `/etc/<instance>/odoo.conf` in addition to the
default `/etc/odoo/<instance>/<instance>.conf`.

## Read-only guarantee

The audit is read-only with respect to **server configuration**: it never produces or applies an install,
configuration, or deletion command — see the
[read-only requirement in the spec](../openspec/specs/server-audit/spec.md).

Two operator-initiated extras are the only things it may write or actively probe, both harmless:

- **Export the report** — when you opt in, it writes a single report file to the path you choose (default under
  `./reports/`, relative to where you launched the tool as root). This is the only file the audit creates: a new
  file (an existing file, or a link in its place, is refused) readable by root only.
- **Active TLS checks** — when you opt in with an expiry threshold, it runs read-only `openssl` certificate
  checks; no certificate or service is modified.

## Related

- [Instance management](operations/instance-management.md)
- [Configuration reference](configuration-reference.md)
