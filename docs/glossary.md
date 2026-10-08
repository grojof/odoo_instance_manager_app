---
type: reference
title: "Glossary"
description: "Domain vocabulary used across Odoo Instance Manager: instance, filestore, jail, neutralize, and more."
tags: [glossary, reference, vocabulary]
audience: [operator, contributor]
updated: 2026-07-03
---

# Glossary

Terms as they are used in this project.

- **Instance** — one deployed Odoo Community environment, identified by a name that derives its user, home,
  config, service, ports, and Nginx/TLS paths (see [configuration reference](configuration-reference.md)).
  Multiple instances co-exist on one host ("multi-instance").

- **Multi-instance** — running several independent Odoo instances on the same server, each with its own
  service, ports, config, and (usually) database, isolated by name-derived paths.

- **Base instances directory** — `/opt/odoo`; each subdirectory is an instance home.

- **Instance home** — `/opt/odoo/<instance>`, containing `odoo/` (the cloned source), `addons-oca/`,
  `addons-custom/`, and the `venv/`.

- **Plan** — an ordered `list[Command]` an action builds *before* executing anything. Each `Command` is a
  `(description, command)` pair. Plans are previewed, then applied. See [architecture](architecture.md).

- **Planner** — a **pure** function in `planners.py` that builds a plan and performs no I/O or execution.

- **Filestore** — Odoo's on-disk store for attachments/binaries, under
  `<data_dir>/filestore/<database>` (default `data_dir` is `<home>/.local/share/Odoo`). Backed up and moved
  alongside the database.

- **data_dir** — Odoo's data directory (from the config, or the default under the instance home) that contains
  the filestore.

- **Copied vs moved** — restore/duplicate semantics. **Copied** regenerates the target's `database.uuid` so it
  is a distinct database; **moved** keeps the UUID.

- **Neutralize** — make a copied database unable to act as production: crons, mail (servers off, credentials
  dropped, a mail sink so `odoo.conf`'s server is never used), fetchmail, payment providers, carriers, OAuth,
  calendar tokens, webhooks, IAP, EDI/SII modes, queued jobs and the base URL. Checked afterwards; see
  `instance_manager/neutralise.py` for each rule and its source.

- **database.uuid** — Odoo's per-database identifier stored in `ir_config_parameter`; regenerated in copied
  mode.

- **Jail** — a Fail2ban unit that watches a log and bans offending IPs. This tool creates a per-instance
  `odoo-auth-<instance>` jail plus base jails (`sshd`, `nginx-http-auth`, `nginx-botsearch`, `recidive`).

- **Real client IP** — the actual visitor IP, as opposed to the proxy/gateway IP. Behind Nginx, Odoo must log
  the real client IP (via forwarded headers) or Fail2ban would ban your own infrastructure. See
  [Fail2ban security](security/security-fail2ban.md).

- **Phrase confirmation** — typing an exact phrase (e.g. `DELETE <instance>`) to authorize a destructive
  action, on top of the normal confirm step.

- **Total purge** — the most destructive action: removes an instance plus its Linux user, logs, filestore
  root, the databases its role owns (or named like it), and PostgreSQL roles. Gated by `DELETE-ALL <instance>`.

- **Capability spec** — an OpenSpec specification under `openspec/specs/<capability>/spec.md` describing a
  slice of behavior as requirements and scenarios; the behavior source of truth.
