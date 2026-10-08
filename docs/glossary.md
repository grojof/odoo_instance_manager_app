---
type: reference
title: "Glossary"
description: "Domain vocabulary used across Odoo Instance Manager: instance, filestore, jail, neutralize, and more."
tags: [glossary, reference, vocabulary]
audience: [operator, contributor]
updated: 2026-10-08
---

# Glossary

Terms as they are used in this project. Each entry defines the term and links to the page that holds its details.

- **Instance** — one deployed Odoo Community environment, identified by a name that derives its user, home,
  config, service, ports, and Nginx/TLS paths (see [configuration reference](configuration-reference.md)).
  Several instances co-exist on one host.

- **Base instances directory** — `/opt/odoo`; each subdirectory is an instance home.

- **Instance home** — `/opt/odoo/<instance>`, containing `odoo/` (the cloned core), `addons-oca/`,
  `addons-custom/`, and the `venv/`.

- **Core** — the Odoo repository an instance runs: official Odoo (`odoo/odoo`) or OCA's **OCB** (`OCA/OCB`, the
  same branches with backported fixes). Chosen at install; a replica runs its source's core.

- **Support matrix** — the per-version facts the install follows: each Odoo version's Python range, the Python
  uv installs when the host's cannot build it, the setuptools pin and the PostgreSQL floor
  ([supported platforms](platforms.md#odoo-versions)).

- **uv** — the tool that installs a Python interpreter into `/opt/odoo-python` when the host's `python3`
  cannot build an Odoo version; one pinned release, checked against its published SHA-256.

- **Plan** — an ordered `list[Command]` an action builds *before* executing anything. A `Command` has a
  description, the command, the secrets it needs (in its environment, never in the command) and what the
  preview shows. See [architecture](architecture.md).

- **Planner** — a **pure** function in `planners.py` that builds a plan and performs no I/O or execution.

- **data_dir** — Odoo's data directory: filestores and sessions. New installs set it to
  `/var/lib/odoo/<instance>`, outside the home; an instance without `data_dir` in its `odoo.conf` uses Odoo's
  default, `<home>/.local/share/Odoo`.

- **Filestore** — Odoo's on-disk store for attachments, `<data_dir>/filestore/<database>`. Backed up, restored
  and copied alongside its database.

- **Copied vs moved** — restore/duplicate semantics. **Copied** gives the target its own identity
  (`database.uuid`, `database.secret`, creation date); **moved** keeps it.

- **Neutralize** — make a copied database unable to act as production, before any Odoo can see it, and check it
  afterwards. The rules are listed in [instance management](operations/instance-management.md#restore-and-duplicate--copied-vs-moved).

- **Mail sink** — the one active outgoing mail server a neutralised database keeps, pointing at a host that does
  not resolve, so Odoo never falls back to the `smtp_server` of `odoo.conf`.

- **Jail** — a Fail2ban unit that watches a log and bans offending IPs: the base jails and a per-instance
  `odoo-auth-<instance>` jail ([Fail2ban protection](security/security-fail2ban.md)).

- **Real client IP** — the actual visitor IP, as opposed to the proxy/gateway IP. Behind Nginx, Odoo must log
  the real client IP (via forwarded headers) or Fail2ban would ban your own infrastructure.

- **Phrase confirmation** — typing an exact phrase (e.g. `DELETE <instance>`) to authorize a destructive
  action; asked before the plan is shown.

- **Total purge** — the most destructive action: an instance with its Linux user, logs, jail, databases and
  roles, gated by `DELETE-ALL <instance>` ([instance management](operations/instance-management.md#removing-an-instance)).
