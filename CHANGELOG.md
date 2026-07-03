# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it cuts tagged releases.

## [Unreleased]

### Added

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
