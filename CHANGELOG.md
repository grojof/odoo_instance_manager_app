# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it cuts tagged releases.

## [Unreleased]

### Changed

- Aligned the specs and docs with actual behavior (config update replays the full base setup; audit read-only
  is qualified to an optional operator-initiated report file + active TLS checks; UFW is a documented runtime
  prerequisite for Fail2ban banning; cleanup drops the DB role by install mode; `list_db = True` security
  note; Python 3.12+ stated as the floor).
- Reworded the app-server-IP prompt to drop a non-existent UFW reference (only a `pg_hba` rule is added).

### Fixed

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
