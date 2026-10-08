# Contributing

Thanks for helping improve Odoo Instance Manager. This project manages production Odoo servers, so changes
are held to a careful, spec-first standard.

## Ground rules

- **Spec-first for non-trivial changes.** New behavior or changes to existing behavior are captured as an
  OpenSpec change before code. See [Workflow](#workflow) below and
  [`docs/architecture.md`](docs/architecture.md) for how the layers fit together.
- **Never weaken a safety control to make something work.** The preview → confirm → apply gate, phrase
  confirmations, and identifier validation are load-bearing (see
  [`docs/decisions/0001-plan-preview-apply-safety.md`](docs/decisions/0001-plan-preview-apply-safety.md)).
- **Keep planners pure.** Functions in `planners.py` build `list[Command]` and must not execute anything or
  perform I/O. Execution lives in `system.py`; orchestration in the `workflows/` package.
- **Validate and quote every operator-supplied value** that reaches a shell command or SQL string. Use the
  existing `_quote`/`shlex.quote` and the identifier validators — do not interpolate raw input.

## Project layout

| Path | Role |
|------|------|
| `odoo_instance_manager.py` | Entry point, root check, main menu |
| `instance_manager/models.py` | `InstanceConfig`, identifier validation, path derivation |
| `instance_manager/support.py` | Per-version facts: Python, setuptools, PostgreSQL floor, cores, pinned uv |
| `instance_manager/neutralise.py` | Neutralisation rules for copied databases (pure SQL builders) |
| `instance_manager/planners.py` | Pure command-plan builders (config/systemd/nginx/fail2ban) |
| `instance_manager/system.py` | Execution primitives, existence checks, preview/apply |
| `instance_manager/prompts.py` | Interactive input, file picker, phrase confirmation |
| `instance_manager/ui.py` | Terminal rendering |
| `instance_manager/workflows/` | Menus, plan assembly, discovery/audit — one module per capability over `common.py` |
| `openspec/specs/` | Capability specifications (the source of truth for behavior) |
| `docs/` | User- and operator-facing documentation |

## Conventions

- Python 3.12+, `from __future__ import annotations`, standard library only (no third-party runtime deps).
- Files are UTF-8 with LF newlines and a final newline.
- Conventional Commits in the imperative mood; one logical change per commit. No AI-attribution trailers.
- Match the surrounding style: small functions, early returns, type hints, Spanish operator-facing strings.

## Dev loop

Install the project with dev tooling and run the same gate CI runs:

```bash
pip install -e ".[dev]"      # editable install + pytest, ruff
ruff check                   # lint (config in pyproject.toml)
pytest                       # unit tests (tests/)
openspec validate --specs    # specs are well-formed
python3 tools/verify_data_safety.py  # run the generated backup/retention/delete/copy commands
python3 tools/verify_install_runtime.py --clone 14=/path/odoo-14.0 --clone 16=/path/odoo-16.0
python3 tools/verify_neutralisation.py --odoo 18=/path/venv/bin/python:/path/odoo-18.0
python3 tools/verify_ops_configs.py    # nginx -t and fail2ban on the generated config
python3 tools/verify_secrets.py        # secrets in no process argument, preview or error
python3 tools/verify_privilege.py      # certificates, downloads, venv replication, neutralisation as owner
python3 tools/verify_postgres_setup.py # PostgreSQL install steps: port, scram, listen_addresses, pg_hba
```

`tools/verify_data_safety.py`, `tools/verify_secrets.py`, `tools/verify_privilege.py`,
`tools/verify_postgres_setup.py` and `tools/verify_ops_configs.py` also run in CI.
`tools/verify_data_safety.py` executes the generated scheduled-backup script, the
retention prune and the delete step against stub binaries, and the template copy, forced drop and purge
discovery against a PostgreSQL cluster of its own (it needs `initdb` and refuses to run as root). Run it after
changing any of those.

`tools/verify_privilege.py` runs the certificate steps with real `openssl` (a key that does not match must leave
the live files untouched, a hostile file name must stay a name), the wkhtmltopdf and venv-replication steps
against stubs, and the neutralisation as the copy's owner against a PostgreSQL cluster of its own, where a
trigger in the copy tries to make its owner a superuser. Run it after changing those planners or
`_post_db_mode_commands`.

`tools/verify_postgres_setup.py` runs the PostgreSQL steps of an install against a cluster of its own on a port
other than 5432, storing md5 by default as PostgreSQL 13 does and with a `conf.d` file, and checks the role's
scram password, `listen_addresses` set with one restart, and the `pg_hba` rule added once. Run it after changing
those planners.

`tools/verify_install_runtime.py` is not part of CI: it downloads the pinned uv (and refuses a wrong
checksum), installs the interpreter the matrix picks, builds a real venv for each Odoo checkout you pass and
starts `odoo-bin --version`; for Odoo <= 16 it also shows the unpinned setuptools breaks it. It needs network
access and the build dependencies, and writes only to a temp directory. Run it after changing
`instance_manager/support.py` or the venv steps.

`tools/verify_neutralisation.py` installs real Odoo databases (an Odoo venv and checkout per version) in a
PostgreSQL cluster of its own, arms them like production, runs the duplication's own seed, neutralisation,
check and hand-over commands, and has Odoo itself try to send a mail from the copy. Run it after changing
`instance_manager/neutralise.py` or the duplication/restore plans.

`tools/verify_ops_configs.py` downloads the distribution's nginx package (`apt-get download`, extracted, never
installed) and fail2ban's source release, then runs `nginx -t`, `fail2ban-regex` and `fail2ban-client -t` on the
generated vhosts, filter and jails, including their rollbacks. It runs fail2ban 1.1.0, 1.0.2 and 0.11.2 (the
older two on a Python 3.11/3.10 and 3.9/3.8 found on PATH or through uv, converted with lib2to3 as the
distributions do), and has each ban a stub ufw. It also runs the staged writes' failure modes and logrotate's
rollback. Run it after changing those planners.

CI (`.github/workflows/ci.yml`) runs ruff, pytest, a byte-compile, `openspec validate`, and the eunomai
`docs-check` / `provenance-check` gates on every push and PR to `main`.

Tests use stdlib `unittest` (collected by pytest) so they run with `python -m unittest discover -s tests`
even without dev deps installed. Ruff enforces F/B/I/UP/E/W; `E501` (line length) is deliberately deferred
because many long lines are embedded shell/SQL command strings — aim for ≤100 cols in new code.

## Workflow

For non-trivial changes, use the OpenSpec flow:

```
/opsx:explore        # think through the change (optional)
/opsx:propose <name> # create the change: proposal, design, tasks, spec deltas
/opsx:apply          # implement the tasks
/opsx:archive        # fold the spec deltas into openspec/specs/ and archive
```

Validate specs and changes at any time:

```bash
openspec validate --specs
openspec list --specs
```

## Before opening a PR

- Run the tool against a **disposable VM or container**, never a production host, to exercise the affected
  menu path end to end.
- Confirm the affected capability spec under `openspec/specs/` still matches the behavior (update it via a
  change when behavior shifts).
- Keep the docs honest: if behavior changes, update the affected `docs/` page and the README map in the same
  change.
