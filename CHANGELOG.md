# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it cuts tagged releases.

## [Unreleased]

### Added

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
