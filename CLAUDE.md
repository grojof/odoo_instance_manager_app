# Odoo Instance Manager — AI Agent Guide (CLAUDE.md)

Interactive, **root-run** Python CLI to install, maintain, and audit multi-instance **Odoo Community**
servers on Ubuntu 24.04. It never mutates the host directly: every action assembles a command **plan**,
previews it, and applies it only after confirmation. This file is the single authored source of truth for AI
agents working *on* this project.

## Project boundary & paths

- **This repository is the project root.** A single Python package, no nested repos.
- `odoo_instance_manager.py` — entry point (root check, UTF-8 console, main menu).
- `instance_manager/` — the package, in strict layers (see `docs/architecture.md`):
  - `models.py` — `InstanceConfig`, identifier validation, path derivation.
  - `planners.py` — **pure** builders returning `list[Command]` (odoo.conf, systemd, nginx, fail2ban, TLS).
    No I/O, no execution.
  - `system.py` — execution primitives, existence probes, `preview_commands`/`apply_commands`.
  - `prompts.py` — interactive input, file picker, `confirm_with_phrase`.
  - `ui.py` — terminal tables and styling.
  - `workflows/` — a package split by capability (install, manage, backup_restore, fail2ban, firewall,
    services, purge, report, health, diskusage, addons, logrotate, scheduled_backup, …) over a shared
    `common.py`; menus, plan assembly, discovery, and the read-only audit.
- `openspec/specs/` — the **behavior source of truth** (one spec per capability). Changes live in
  `openspec/changes/`.
- `docs/` — user/operator docs, each with frontmatter. Grown surfaces are grouped into folders
  (`docs/operations/`, `docs/security/`); setup/reference/audit pages stay flat at `docs/`; `docs/decisions/`
  holds ADRs. The README is the routable map.
- Operator-facing strings are **Spanish** (matching the current UI); docs and specs are **English**.

## Conventions

- Python 3.12+, `from __future__ import annotations`, **standard library only** (no third-party runtime deps).
- Files are UTF-8, newlines LF, final newline at EOF.
- Conventional Commits, imperative mood, one logical change per commit. No AI-attribution trailers.
- Match the surrounding code: small functions, early returns, type hints.
- **Keep planners pure** — building a command is not running it. Execution belongs to `system.py`.
- **Quote and validate every operator-supplied value** reaching a shell command or SQL string (use `_quote`
  / `shlex.quote` and the identifier validators). Never interpolate raw input.

## How to work in this project

- **Non-trivial changes are spec-first.** Capture intent and a short plan before code, and keep a record of
  what changed and why. Behavior is specified in `openspec/specs/`; use the OpenSpec `/opsx:*` flow
  (`/opsx:explore → /opsx:propose <name> → /opsx:apply → /opsx:archive`) and validate with
  `openspec validate --specs`.
- **Preview → confirm → apply is inviolable.** Every host-mutating action must go through a previewed plan;
  destructive/data actions must keep their exact phrase confirmation. Do not add a code path that mutates the
  system without a plan. (See `docs/decisions/0001-plan-preview-apply-safety.md`.)
- **Keep docs honest.** When behavior changes, update the affected `docs/` page and the README map in the
  same change.
- **Keep the changelog and version in lockstep.** User-facing changes go under `## [Unreleased]` in
  `CHANGELOG.md` (Keep a Changelog format) as they land. To cut a release, follow **SemVer**: rename
  `[Unreleased]` to `[<version>] - <YYYY-MM-DD>` (leave a fresh empty `[Unreleased]` on top), bump `version`
  in `pyproject.toml` to match, add the `[<version>]` compare/tag link at the bottom, then tag `v<version>`
  and publish a GitHub release. The tag, the `pyproject` version, and the changelog heading must always agree.
- **Secure by default.** Validate input at boundaries, never hardcode secrets, and quote everything that
  reaches a shell or SQL. The tool runs as root — assume every input is attacker-controlled.
- **Add dependencies deliberately.** This project is standard-library-only by design; introducing a runtime
  dependency is itself a decision worth an ADR — pin it, scan for known CVEs, and justify it.
- **Some actions are irreversible or sensitive** — force-push, history rewrite, secret access, deleting
  instances/databases: pause and confirm first. Safe-controls hooks enforce a floor when installed (see
  `docs/security/safe-controls.md`).

## Safe controls

- Runtime guardrails come from the **eunomai** Claude Code plugin's `PreToolUse` hooks (ask-by-default on
  force-push / `rm -rf` / secret access; deny on AI-attribution commit trailers). Fail-open, a floor-raiser,
  not a security boundary.
- Static path rules use the native `permissions` baseline in `.claude/settings.json` — see
  `docs/security/safe-controls.md`.

## Checks

Structural, read-only gates (run from the project root):

```bash
openspec validate --specs        # every capability spec is well-formed
# eunomai docs-check / provenance-check via the installed plugin/CLI
```
