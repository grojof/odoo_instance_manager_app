# Tasks

## 1. Spec deltas

- [x] 1.1 addon-inventory: ADDED "Python dependency audit".
- [x] 1.2 data-backup-restore: MODIFIED "Duplication" (replica replicates source venv packages).
- [x] 1.3 `openspec validate python-deps-replicate-and-audit --strict` passes.

## 2. Code — audit (addon inventory)

- [x] 2.1 `addons.py`: `_manifest_python_deps(text)` via `ast.literal_eval` (safe; skip malformed).
- [x] 2.2 `addons.py`: collect declared python deps per addon; `_venv_can_import(config, module)` check.
- [x] 2.3 `addons.py`: render a "Required Python packages" table (module → requiring addons → installed?),
      included in the export sections.

## 3. Code — replica venv replication

- [x] 3.1 `backup_restore.py`: replica offers to replicate the source venv packages
      (`pip freeze` filtered → `pip install` into the target venv).

## 4. Docs, i18n & changelog

- [x] 4.1 `docs/operations/addon-inventory.md` + `instance-management.md`.
- [x] 4.2 i18n: Spanish entries for the new prompts/labels.
- [x] 4.3 `CHANGELOG.md` `[Unreleased]`.

## 5. Verify

- [x] 5.1 `openspec validate --strict`, `ruff`, `pytest`, `compileall` pass.
