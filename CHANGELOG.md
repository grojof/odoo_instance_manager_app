# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it cuts tagged releases.

## [Unreleased]

### Security

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
