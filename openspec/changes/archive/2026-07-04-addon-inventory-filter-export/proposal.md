# Addon inventory: installed/all filter and export

## Why

The addon inventory lists **every** discovered module per origin. On a real instance that is a very long
list, and when the operator has checked a database they usually only care about what is actually installed.
There is also no way to save the inventory — unlike the server-audit report, which can be exported to a file.

## What changes

- **instance addon-inventory**
  - **Installed-state enrichment (MODIFIED):** after checking a database, the operator can choose to list
    **only installed** modules or **all** discovered modules. Only-installed hides not-installed modules and
    any group left empty.
  - **Optional inventory export (ADDED):** after rendering, offer to export the inventory (with the active
    filter) to a single text file at an operator-chosen path (default under `./reports/`), mirroring the
    server-audit report export. Declining writes nothing.

## Impact

- Spec: `addon-inventory`.
- Code: `instance_manager/workflows/addons.py` (filter prompt + pure `_is_installed`/`_build_group_rows`
  helpers + `_maybe_export_inventory`). No new runtime dependency (stdlib `datetime`/`os`; `strip_ansi` reused).
- Docs: `docs/operations/addon-inventory.md`; `CHANGELOG.md` `[Unreleased]`.
- Tests: `tests/test_addons.py` (installed predicate + row filtering).
