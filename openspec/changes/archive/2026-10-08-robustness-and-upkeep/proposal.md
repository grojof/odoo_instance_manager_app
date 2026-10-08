# Robustness and upkeep

## Why

The last group of the second audit:

- **Interruptions and unexpected errors.**
  - Ctrl+C during a long step returned to the menu while the step (bash and what it started) kept running.
  - An unreadable file, a host answering something that is not HTTP, a missing picker directory, or Ctrl+C at
    the language prompt ended in a traceback.
- **Translations.** The posture and paths tables showed English labels in Spanish. 86 catalog entries no code
  used any more, and one Spanish string had a typo.
- **Verifiers that passed while verifying nothing.**
  - `verify_neutralisation` with no `--odoo` and `verify_install_runtime` with no `--clone`;
  - `verify_ops_configs` when the nginx package had no binary;
  - `verify_data_safety` when run as root.
- **Python requirement.** `docs/platforms.md` listed Ubuntu 22.04 and Debian 11/12, but one line used Python 3.12
  syntax, so the tool did not start on their `python3`.
- **The file picker** took an out-of-range number as a path.
- **Scheduled backups** of an instance with a remote database dumped the local server, and the status did not
  show whether the last run made a backup.
- **Release workflow.**
  - It published any `v*` tag from any branch, always as the latest release, and did not run the verifiers.
  - ruff and build were unpinned.
- **Docs and CLI.**
  - `AGENTS.md` missed two modules and its checks; CONTRIBUTING asked for Spanish strings.
  - The README overstated the cleanup; the audit page named sections the report does not print.
  - The CLI ignored `--help`.

## What changes

- **Steps.** A step runs in its own process group: Ctrl+C terminates it (then kills it) and waits for it.
- **Errors.** A last-resort handler names an error and returns to the menu. The language prompt, picker and
  health probe are hardened. `--help` and `--version` work without root.
- **Translations.** Translated posture and path labels, dead entries removed, the typo fixed. Tests fail on a
  missing or an unused entry.
- **Verifiers.** They fail when they verify nothing; a skip in CI is a failure. A new check runs Ctrl+C against a
  real step.
- **Python 3.9+.** The one 3.12-only line is fixed; `requires-python >=3.9`, ruff targets py39, and CI runs the
  suite on 3.9.
- **Scheduled backups.** A remote database or a missing one is refused, and the last run's result is shown.
- **Release.** It runs the CI workflow first, publishes only tags on `main`, marks pre-releases as such, and pins
  ruff, build and twine.
- **Docs and the delete flow.** AGENTS.md, CONTRIBUTING, README, server-audit and platforms are brought in line
  with the code, and the manage menu leaves an instance once it is deleted.

## Impact

- Specs: `execution-safety`, `scheduled-backups`, `ui-localization`.
- Code: `system.py`, `prompts.py`, `odoo_instance_manager.py`, `planners.py`, `i18n.py`,
  `workflows/{health,manage,scheduled_backup}.py`.
- Tools, CI and release: `tools/verify_*`, `.github/workflows/{ci,release}.yml`, `pyproject.toml`.
