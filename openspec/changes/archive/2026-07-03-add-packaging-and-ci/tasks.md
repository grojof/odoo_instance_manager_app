# Tasks

## 1. Packaging

- [x] 1.1 Add `pyproject.toml` (metadata, `requires-python = ">=3.12"`, AGPL license, console entry point,
  `dev` extras, setuptools module/package declaration).
- [x] 1.2 Add `[tool.ruff]` (line-length 100, py312, select E/F/I/UP/B/W, ignore E501) and
  `[tool.pytest.ini_options]` (`testpaths = ["tests"]`).
- [x] 1.3 Verify editable install succeeds (`pip install -e ".[dev]"`) and ruff/pytest read their config with
  no args.

## 2. Lint baseline

- [x] 2.1 Apply ruff safe autofixes (import ordering, redundant open modes) so `ruff check` starts green.
- [x] 2.2 Confirm zero F (pyflakes) findings and that the full selected ruleset passes.

## 3. CI workflow

- [x] 3.1 Add `.github/workflows/ci.yml`: ruff → pytest → byte-compile → `openspec validate --specs` →
  eunomai `docs-check`/`provenance-check` (pinned eunomai checkout), on push/PR to `main`.

## 4. Docs

- [x] 4.1 Document the dev loop (install, ruff, pytest, openspec validate) in `CONTRIBUTING.md`.
- [x] 4.2 Note the new packaging/CI in `CHANGELOG.md`.

## 5. Verify

- [x] 5.1 `pip install -e ".[dev]"`, `ruff check`, `pytest`, `openspec validate --specs` all pass locally.
- [ ] 5.2 CI run is green on the pull request.
