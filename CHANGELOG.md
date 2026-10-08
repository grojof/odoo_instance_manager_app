# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it cuts tagged releases.

## [Unreleased]

### Added

- **Per-version install.** A support matrix for Odoo 12–19 (`instance_manager/support.py`): the venv is built
  with the host `python3` only when it can build the version, else with a CPython installed by uv (pinned,
  SHA-256-checked) into `/opt/odoo-python`. setuptools is pinned per version (`<58` up to 13, `<81` up to 16) and
  Odoo 12's `pyldap` is replaced. Before, Odoo 14 did not install on Ubuntu 24.04 (its requirements stop at
  Python 3.10) and Odoo 15–16 did not start there (setuptools 81 removed the `pkg_resources` they import).
- **OCB.** The install asks for the core — official Odoo or OCA's OCB; a replica runs the source's core.
- New instances get `without_demo = all` (Odoo ≤ 18) and `data_dir = /var/lib/odoo/<instance>`, outside the
  home. The PostgreSQL floor of the Odoo version is checked when PostgreSQL is installed.

### Changed

- **Interface text is English throughout**, with Spanish only through the catalog: about twenty Spanish labels
  left in the code (report headers, certificate states, prompts) are now English keys. The catalog is written
  English → Spanish, the direction it is read; written the other way and inverted, it silently merged English
  strings whose Spanish matched. A test fails when a UI string has no Spanish entry.
- CI also runs `tools/verify_data_safety.py`, `tools/verify_secrets.py` and `tools/verify_ops_configs.py`, and
  `pytest` works without installing the package (`pythonpath`).
- *Install Odoo instance + PostgreSQL* no longer opens PostgreSQL to the network (`listen_addresses`, `pg_hba`).
- The systemd unit follows Odoo's own (`KillMode=mixed`) and starts after a local PostgreSQL.
- apt installs run unattended and wait for the dpkg lock.
- The branch defaults to `<version>.0`, and the version must be one the matrix knows.

- Backups are named `<instance>--<db>--<timestamp>` and kept per database; older `<instance>_<timestamp>`
  files are still pruned, as their own group. Backup directories are private (`700`).
- Database listings no longer match by name prefix: the role's databases and the one named like it.
- The duplication confirmation phrase is `DUPLICATE <instance>` (was `DUPLICAR`).

### Fixed

- **Passwords were visible to every local user.** Each database password went into the command text
  (`PGPASSWORD=… psql`), so it was in the arguments of the running step, which `ps` shows any user (another
  instance's Odoo user included), and it was printed in the plan preview and in a failed step's error, as were
  `odoo.conf`'s passwords. Steps now carry secrets in their environment, SQL with a password goes to psql on
  stdin, files are written atomically with their content in the environment, the preview masks secrets, and a
  failure names the step. Database probes give up after 10 seconds instead of minutes.
- The addon dependency check reported packages declared by their distribution name (`python-stdnum`) as
  missing; it now asks by distribution name first, as Odoo does. The health check now reaches a Unix-socket
  database (`db_host = False`), a failed export no longer crashes the CLI, and the server report's database
  list no longer matches by name prefix.
- **The v1.2.0 wheel did not run**: it left out `instance_manager.workflows`. Packages are now found, and CI and
  the release build the wheel and import it from a clean venv; the release fails when the changelog has no
  section for the tag.
- **fail2ban**: a missing log (nginx jails without nginx) made fail2ban refuse its whole configuration, sshd jail
  included; jails were written before being validated. They are now staged and kept only if
  `fail2ban-client -t` accepts them, and nginx jails are written only with nginx logs. The Odoo filter missed
  Odoo 19's line and its test passed with no match; it now matches 12–19 and the test needs a match. Web and Odoo
  bans block only the web ports (ufw's `Nginx Full`), never SSH.
- **UFW**: deleting by number could delete the SSH allow after fail2ban shifted the list; the delete now checks
  the rule is unchanged. The SSH port is detected.
- **nginx**: a vhost was enabled before `nginx -t`, so a failed change stayed enabled; it is now rolled back.
  The HTTP vhost limited uploads to 1 MB. The HTTPS vhost now follows Odoo's deployment guide (HSTS, Secure
  session cookie, TLS settings, gzip).
- **Copies were not neutralised.** Only crons, mail servers and fetchmail were switched off, each failure
  ignored; with no mail server active Odoo falls back to `odoo.conf`'s `smtp_server` and a local MTA relayed real
  mail, and payment providers, carriers, OAuth, calendars, webhooks, IAP, EDI/SII and the base URL stayed live. The
  copy was also visible to the instance's cron worker before any of it ran. Now the catalogue of Odoo's own
  `neutralize.sql` (extended to 12.0–19.0 and OCA modules) is applied as one statement with a mail sink, checked
  afterwards, and the copy is handed to its role only once neutralised (a restore stops the service meanwhile).
  Copied mode also renews `database.secret`. New read-only action: *Check a copy is neutralised*.
- **Delete instance kept no filestore.** Without a `data_dir` in `odoo.conf`, the filestores live in the
  instance home, which the delete removed even when you answered "No" to deleting the filestore. The data dir
  is now moved to `/var/backups/<instance>/kept-data-dir-<timestamp>` first; only the filestore you name is
  deleted. The backup timer is removed too.
- **Purge dropped other instances' databases.** It selected `<instance>%` (and `_` is a LIKE wildcard), so
  purging `shop` dropped `shop2` and `shop_eu`. It now selects the databases its role owns and the one named
  like the instance; look-alikes are listed as not selected. It drops the role you name, and removes the
  backup timer and the fail2ban jail (fail2ban refuses to start when a jail's log is missing).
- **Duplicate instance could drop production.** A refresh dropped whatever target database was typed. It now
  refuses the source instance or database as target and a database owned by another role, and asks before
  overwriting the target's own. A template copy across roles is refused (its tables would keep the source
  owner); the template copy now blocks and always reopens the source. Drops use `dropdb --force`.
- **Scheduled backups reported success when the dump failed**, wrote world-readable dumps, and their retention
  removed other instances' and other databases' dumps. The script now fails on a failed or unreadable dump, a
  missing filestore or a failed archive, leaves no partial file, writes private files and prunes per database.
- **Restore** moves an existing filestore aside instead of deleting it, and hands the restored files to the
  instance user.
- **Update existing configuration** replaced `odoo.conf` (losing `data_dir`, `smtp_*`, extra addons paths),
  re-ran apt and pip, did not restart the service, and changed the DB password only in the file. It now merges
  the file, reinstalls nothing, sets a new password on the local role, restarts a running service, and reads
  the version and domain from the instance.
- **Operator values reached a root shell unquoted** (repo branch, domain, app-server IP, database names, and
  existence probes that run before the preview). They are validated — database names with Odoo's own pattern —
  and prompts ask again; probes quote their argument.

## [1.2.0] - 2026-07-04

### Added

- **Duplicate database** (instance management): a database-only duplication with the same copy method
  (template / `pg_dump | pg_restore --role`) and copied/moved + neutralize semantics as instance duplication,
  plus an optional filestore copy — without provisioning or touching any service/config. Local PostgreSQL only.
- **Addon Python dependency audit.** The addon inventory now reports the Python packages the instance's addons
  declare (`external_dependencies['python']`, parsed safely) and whether each **imports in the instance venv**
  (`OK`/`MISSING`) — so you can spot missing addon dependencies. Included in the export.
- **Replica replicates the source venv packages.** When duplicating into a new instance, the tool offers to
  install the source venv's Python packages into the target venv (a filtered `pip freeze`), so addon
  dependencies the source installed beyond `requirements.txt` are present in the replica (avoiding runtime
  errors).

### Changed

- **Database listings are scoped to the instance's role.** When managing an instance (and when picking a source
  DB), the tool now lists only databases **owned by the instance's DB role** (or named after it) instead of
  every database on the server. The total-purge flow (main menu) prompts for the instance's DB user and
  discovers its databases by **owner as well as name prefix**, so all associated databases are cleaned.

- **Grouped instance-management menu.** The management menu is now organized into submenus — **Status &
  health**, **Configuration**, **Backups & duplication** — plus a top-level **Delete instance**, instead of one
  long flat list.
- **Orchestrated instance duplication (replica or refresh).** *Duplicate instance* now creates a **fully
  working** target instead of only copying the database. If the target does not exist it provisions the whole
  instance (system user, home, Odoo checkout at the source's version, virtualenv, config, systemd service, and
  optionally Nginx) following the **same production-hardening prompts as a fresh install** (secrets, `list_db`,
  `dbfilter`, workers, `db_sslmode`, wkhtmltopdf) with auto-suggested non-colliding ports, then seeds it from
  the source. A replica fronting Nginx must use a **domain not already served by another vhost** (instances
  share 80/443 and Nginx routes by `server_name`), which the tool now enforces. If the target already exists it **refreshes it in place** (stop, replace DB + filestore, restart) —
  the "keep dev up to date with production" flow. The database copy method is selectable: robust
  `pg_dump | pg_restore --role` that reassigns ownership for cross-user targets, or a fast template copy.
  Local PostgreSQL only (use Backup + Restore for a remote DB). `plan_odoo_base_setup` gained a `start_now`
  flag so the target is provisioned before its database exists and started after seeding. Every seeded database
  is **isolated to its owner** (`CONNECT` revoked from `PUBLIC`, granted to the owning role) so an instance's
  role cannot reach other instances' databases, and the duplicated **data dir is owned by the target user** so
  Odoo can create its `sessions`/`filestore` (fixing a `PermissionError` on first run).

## [1.1.0] - 2026-07-04

### Added

- **Addon inventory: installed/all filter and export.** After checking a database, the inventory can list
  **only installed** modules (default) instead of all — the full list is long — and it can be **exported to a
  text file** (default under `./reports/`), mirroring the server-audit report export.

- **Secure-by-default provisioning (informed choice).** Blank master/DB passwords now default to a strong
  random secret (stdlib `secrets`), never the guessable instance name; the database manager defaults to
  `list_db = False`; an optional `dbfilter` (recommended, but you can decline to leave the instance
  unfiltered); and remote database hosts get `db_sslmode = require`. Each
  recommended default remains an explicit, warned operator choice at install.
- **Optional wkhtmltopdf** at install: the checksum-verified Qt-patched 0.12.6.1-3 build selected for the
  detected OS codename (SHA-256 pinned; jammy build verified against Odoo's own published checksum), a distro
  package fallback, or skip (warned). Required for Odoo PDF reports.
- **CPU/RAM-derived performance tuning**: `workers = (cpu*2)+1` capped by detected RAM, per-worker memory
  limits, and `limit_request`, all overridable by the operator.
- **Version-adaptive configuration**: the tool detects the OS codename, nginx version, PostgreSQL version and
  the Odoo major, and renders version-correct config — `gevent_port` (Odoo ≥ 16) vs `longpolling_port` (≤ 15),
  the Nginx live-chat location `/websocket` vs `/longpolling/poll`, and the nginx HTTP/2 form
  (`listen … ssl http2` on nginx < 1.25.1, `http2 on;` on ≥ 1.25.1). This fixes a latent broken live-chat
  location on Odoo ≤ 15 and removes the hard tie to Ubuntu 24.04 (now Debian/Ubuntu-family, version-adaptive).
- **Security & production posture audit**: a new instance **Status ▸ Security & production** view and a
  per-instance posture summary in the server-audit report flag `list_db`, guessable default secrets,
  wkhtmltopdf presence/version, worker sizing, remote `db_sslmode`, and `dbfilter`.
- **New doc**: [What it offers & supported platforms](docs/platforms.md) with the OS/nginx/PostgreSQL/Odoo
  support matrix.

### Fixed

- **Duplicating a running instance no longer fails.** A PostgreSQL template copy (`createdb -T`) requires no
  other sessions on the source database, so duplication previously failed with *"source database … is being
  accessed by other users"* unless the operator stopped the source service by hand. Duplication now frees the
  source automatically — blocks new connections, terminates existing sessions, copies, and re-enables the
  source afterward (even if the copy fails), using the instance's own database role. The source database name
  is also validated before being used in SQL.

### Changed

- **Instance status is on-demand.** The management menu no longer dumps every status table on each iteration;
  status is split into selectable **Status ▸ Locations / Detected resources / Config values / Security &
  production** views.
- Documentation is English-canonical: doc pages now quote the English UI labels (the UI defaults to English,
  with Spanish available via i18n), and two in-code Spanish labels were migrated to English.
- Configuration updates for an existing instance now read and preserve its current credentials and
  production-posture settings before regenerating, instead of resetting them.

## [1.0.0] - 2026-07-04

First stable, publicly released version. The interactive manager is feature-complete for installing,
maintaining, and auditing multi-instance Odoo Community servers on Ubuntu 24.04, with the plan → preview →
apply safety model throughout and a fully bilingual (English/Spanish) interface. Standard library only.

### Added

- **Interface language (English / Spanish)**: choose the UI language at startup or via `OIM_LANG`, defaulting
  to **English**. English is the canonical source language (the strings live in English in the code) and
  Spanish is a full translation applied on demand at a few display/input chokepoints (no call-site changes),
  returning the original option value so behavior is language-independent. Coverage is complete — menus,
  prompts, titles, table headers **and string cells**, command/plan descriptions, interpolated status
  messages, and one-off prints all translate — and the yes/no shortcut localizes (`Y/n` / `S/n`). Anything
  without a Spanish translation falls back to its English source. stdlib only.

- **Scheduled backups** (instance management → "Backups programados"): unattended backups on a systemd timer
  (Diario/Semanal/Mensual) — atomic `sudo -u postgres pg_dump` of a chosen DB (local peer auth, no stored
  password) + optional filestore, with retention; plus status and removal.
- **Firewall (UFW)** (main menu): install and manage a UFW baseline — deny incoming / allow outgoing, allow
  SSH (before enabling, to avoid lock-out), HTTP/HTTPS, and optionally PostgreSQL from an app-server IP;
  plus allow-port, delete-rule, and enable/disable. Closes the gap Fail2ban's `banaction = ufw` assumed.
- **Addon inventory** (instance management → "Inventario de addons"): list an instance's modules by origin
  (Odoo core / OCA / custom) with their manifest versions, and optionally mark which are installed in a chosen
  database (from `ir_module_module`).
- **Disk usage & backup retention** (instance management → "Uso de disco y limpieza"): a read-only
  footprint report (home, data dir, logs, backups; free space) and a retention cleanup that keeps the N newest
  backups of each kind (dumps + filestore archives).
- **Instance health check** (instance management → "Comprobar salud"): a read-only check of the systemd
  service, local HTTP responsiveness, database connectivity, and disk usage, flagging any problems. stdlib
  only (uses `urllib`, no `curl` dependency).
- **Log rotation capability** (instance management → "Rotación de logs"): configure a system `logrotate`
  policy for an instance's Odoo log (`/etc/logrotate.d/odoo-<instance>`, `copytruncate`, tunable
  frequency/retention/compression/size) and query the current rotation state (`logrotate -d` preview, log
  sizes, Odoo's built-in `logrotate` flag). Offers to disable Odoo's built-in `logrotate` to avoid double
  rotation. Nginx per-instance logs are left to the distribution's own `nginx` logrotate **when it already
  covers them**; when it does not, the tool offers to rotate them with the modern Nginx-idiomatic method
  (`create` + `postrotate` SIGUSR1 reopen, not `copytruncate`). The Odoo log keeps `copytruncate` (Odoo has no
  log-reopen signal). Query reports who rotates the Nginx logs (distro / this tool / neither).


- Operator UX: DB credentials are now collected once per management session and reused across backup /
  restore / duplicate / delete (with a reuse prompt); passwords are read without echo (`getpass`); the file
  picker can be cancelled; and numeric prompts report the correct range (fixing the "Puerto fuera de rango"
  message on `maxretry`).
- Every menu now shows a consistent `0) Cancelar` entry (unifying the previous three cancel conventions).
- Command output is now streamed live while a plan is applied (via stdlib `subprocess.Popen`), so long steps
  (apt/pip/git/pg_restore) are no longer silent. No new dependency — the tool remains standard-library only.
- Tables now fit the terminal width and wrap long values (paths, addons lists, certificate subjects) instead
  of overflowing and misaligning, so status and report tables stay readable.
- The plan preview is now a wrapped, indented list instead of a table, so long and multi-line commands (e.g.
  the `odoo.conf` heredoc) stay legible; table wrapping is also ANSI-robust so styled long cells wrap too.

### Changed

- Aligned the specs and docs with actual behavior (config update replays the full base setup; audit read-only
  is qualified to an optional operator-initiated report file + active TLS checks; UFW is a documented runtime
  prerequisite for Fail2ban banning; cleanup drops the DB role by install mode; `list_db = True` security
  note; Python 3.12+ stated as the floor).
- Reworded the app-server-IP prompt to drop a non-existent UFW reference (only a `pg_hba` rule is added).

### Fixed

- Deleting an instance and choosing to drop a **non-existent database** no longer crashes: the tool checks the
  database first and warns + skips the drop (and `dropdb` now uses `--if-exists`). More generally, a failed
  command in any non-install flow now returns to the menu with an error message instead of terminating the CLI.
- Stop writing the obsolete `logrotate` option in the generated `odoo.conf` (removed from Odoo in v13, ignored
  since). Log rotation is offered **at install time** (default on), the rotation **Query** now clearly reports
  whether the Odoo log rotation is ACTIVA/INACTIVA, and Configure offers to delete a stale `logrotate` key from
  an existing conf.
- Install the correct `libtiff-dev` package instead of `libtiff5-dev`, which does not exist on Ubuntu 24.04
  and would fail the first `apt-get install` step on the tool's own target OS.
- Server audit report: fix mislabeled columns surfaced while replacing the 27-field positional rows with a
  named `InstanceReportRow` dataclass — the "Python path" and "Workers" columns now show the Python path and
  worker count (were showing the Nginx/filestore hit counts), and the "Nginx cfgs"/"Filestore roots" columns
  now show those hit counts (were showing local DB names / the Nginx count).

- Duplication now places the copied filestore under the **target** instance's data directory (was placed under
  the source instance's, leaving the duplicate without attachments).
- Backups are written atomically (dump/tar to a temp file, promoted on success) and the DB dump and filestore
  archive of one backup now share a single timestamp; the config pre-update backup uses one timestamped
  directory. Prevents 0-byte/partial dumps and mismatched backup pairs.
- Purge database discovery no longer corrupts its `psql` command when the admin password/host contains `-c`
  (removed a fragile string replace).
- Ctrl+C during an install now triggers the same residue cleanup as a failure, and a failed/interrupted
  install returns to the menu instead of crashing the CLI with a traceback.
- `ask_bool` accepts the accented Spanish `sí` (and re-prompts on unrecognized input) instead of silently
  reading it as "no".

### Security

- Reject path-traversal in operator-entered database names before they are embedded in a filestore path that
  is created, archived, or deleted.

- Validate instance and PostgreSQL identifiers on the destructive flows (manage, delete, total purge, and
  duplication target) before any command or SQL is built, closing a root-level shell- and SQL-injection surface
  where a manually-typed instance name reached `rm -f`, `DROP ROLE`, and related commands unquoted. Path
  interpolations in the residue-cleanup builders are now quoted as defense in depth. Tracked as the
  `harden-identifier-validation` OpenSpec change; covered by new unit tests under `tests/`.

### Added

- Packaging (`pyproject.toml`): `odoo-instance-manager` console entry point, `requires-python >=3.12`, AGPL
  license metadata, `dev` extras (`pytest`, `ruff`), and ruff/pytest configuration.
- Continuous integration (`.github/workflows/ci.yml`): ruff, pytest, byte-compile, `openspec validate`, and
  the eunomai `docs-check` / `provenance-check` gates on push/PR to `main`.
- OpenSpec spec-driven-development layer under `openspec/`, with baseline capability specs reverse-engineered
  from the current behavior: `execution-safety`, `instance-provisioning`, `web-proxy-tls`,
  `instance-configuration`, `service-control`, `fail2ban-protection`, `data-backup-restore`,
  `instance-removal`, and `server-audit`.
- Living documentation under `docs/` (architecture, installation, instance management, Fail2ban security,
  server audit, configuration reference, glossary) plus a routable `README.md` map.
- Architecture Decision Records under `docs/decisions/` for the plan/preview/apply safety model and the
  OpenSpec + eunomai adoption.
- Community-health files: `SECURITY.md`, `CONTRIBUTING.md`, this `CHANGELOG.md`.
- `CLAUDE.md` AI-agent guide and a permissions baseline in `docs/safe-controls.md`.

### Note

This entry records the documentation and spec scaffolding added when the project was onboarded to eunomai +
OpenSpec. The manager's runtime behavior (installation, management, security, and audit menus) predates this
changelog and is captured as the baseline specs above.

[Unreleased]: https://github.com/grojof/odoo_instance_manager_app/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/grojof/odoo_instance_manager_app/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/grojof/odoo_instance_manager_app/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/grojof/odoo_instance_manager_app/releases/tag/v1.0.0
