---
type: how-to
title: "Firewall (UFW)"
description: "Install and manage a UFW firewall baseline for an Odoo server."
tags: [security, firewall, ufw]
audience: [operator]
updated: 2026-07-03
---

# Firewall (UFW)

From the main menu **Firewall (UFW)**, the tool installs and manages a UFW firewall for the server. It shows
`ufw status verbose` each time you enter.

## Configure a secure UFW baseline

Applies a secure baseline:

1. Installs UFW if missing.
2. `default deny incoming`, `default allow outgoing`.
3. Allows the **SSH port** you specify — **before** enabling UFW, so you are not locked out.
4. Allows **HTTP (80)** and **HTTPS (443)** if chosen.
5. Optionally allows **PostgreSQL (5432)** from a single app-server IP.
6. Enables UFW (last step).

> **Warning:** double-check the SSH port before applying — a wrong SSH rule with `deny incoming` can lock you
> out of the server. The plan is previewed before anything runs.

## Other operations

- **Allow a port** — `ufw allow <port>/<tcp|udp>`.
- **Delete a rule (by number)** — lists numbered rules and deletes one.
- **Enable / Disable UFW**.

## Relationship with Fail2ban

[Fail2ban](security-fail2ban.md) is configured with `banaction = ufw`, so its bans only take effect when UFW
is installed and active — this menu is how you make that true.

## Related

- [Fail2ban protection](security-fail2ban.md)
- [Installation & provisioning](../installation.md)
