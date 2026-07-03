# Add packaging and CI

## Why

The project has no packaging metadata and no automated verification. It cannot be installed as a command,
its supported Python floor (3.12, required by PEP 701 f-strings in `prompts.py`) is not declared anywhere
enforceable, and nothing runs the tests, the linter, or the spec/doc checks on a change. Every later
improvement — especially the data-operation bug fixes — needs this safety net first.

## What changes

- Add `pyproject.toml`: project metadata, `requires-python = ">=3.12"`, an `odoo-instance-manager` console
  entry point, `dev` extras (`pytest`, `ruff`), and tool config for ruff and pytest.
- Add a GitHub Actions workflow (`.github/workflows/ci.yml`) that, on push/PR to `main`, runs: ruff, pytest,
  a byte-compile, `openspec validate --specs`, and the eunomai `docs-check` / `provenance-check` gates
  (against a pinned eunomai checkout).
- Apply ruff's safe autofixes to the existing sources (import ordering, redundant open modes) so the linter
  starts green.
- Document the dev loop in `CONTRIBUTING.md`.

This is **tooling only** — no runtime behavior changes, so there is no capability spec delta.

## Impact

- New files: `pyproject.toml`, `.github/workflows/ci.yml`.
- Minor mechanical edits from ruff autofix across `instance_manager/*.py` and `odoo_instance_manager.py`.
- `tests/` (added in `harden-identifier-validation`) is now wired into CI.
- Ruff defers `E501` (line length) because many long lines are embedded shell/SQL command strings that must
  not be wrapped; all other value rules (F/B/I/UP/E/W) are enforced and pass.
