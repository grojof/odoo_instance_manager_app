# Tasks

## 1. Spec deltas

- [x] 1.1 addon-inventory: MODIFIED "Installed-state enrichment" (only-installed vs all filter).
- [x] 1.2 addon-inventory: ADDED "Optional inventory export".
- [x] 1.3 `openspec validate addon-inventory-filter-export --strict` passes.

## 2. Code

- [x] 2.1 `addons.py`: pure `_is_installed(state)` + `_build_group_rows(entries, installed, only_installed)`.
- [x] 2.2 `addons.py`: `show_addon_inventory` — offer "only installed vs all" after a DB check; skip empty
      groups; accumulate rendered sections.
- [x] 2.3 `addons.py`: `_maybe_export_inventory(config, sections)` mirroring the report export (default under
      `./reports/`, `strip_ansi`, `makedirs`).
- [x] 2.4 i18n: Spanish entries for the new prompts/labels.

## 3. Docs & changelog

- [x] 3.1 `docs/operations/addon-inventory.md`: document the installed/all filter and the export.
- [x] 3.2 `CHANGELOG.md` `[Unreleased]`.

## 4. Verify

- [x] 4.1 `openspec validate --strict`, `ruff`, `pytest`, `compileall` pass.
