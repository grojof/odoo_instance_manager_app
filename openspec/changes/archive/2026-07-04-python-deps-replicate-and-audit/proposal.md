# Replicate and audit addon Python dependencies

## Why

Odoo modules (especially OCA and custom) often declare **extra Python packages** via their manifest's
`external_dependencies`. Two gaps:

- **Duplication loses them.** A replica's venv is built from Odoo's `requirements.txt` only, so any extra
  package the source venv had is missing — the duplicated instance then errors at runtime.
- **No way to see them.** The addon inventory lists modules but not the Python packages they require, so an
  operator can't tell which extra dependencies an instance needs (or whether they're installed).

## What changes

- **data-backup-restore — Duplication (MODIFIED):** when provisioning a **replica**, the tool SHALL offer to
  replicate the **source venv's Python packages** into the target venv (a filtered `pip freeze` of the source
  installed into the target), so the replica has the same dependencies as the source.
- **addon-inventory — Python dependency audit (ADDED):** the addon inventory SHALL additionally report the
  **Python packages the instance's addons require** — read reliably from each manifest's
  `external_dependencies['python']` — and whether each is **importable in the instance venv** (installed vs
  missing). The audit is included in the inventory export.

## Impact

- Specs: `data-backup-restore`, `addon-inventory`.
- Code: `workflows/addons.py` (`ast`-based manifest dependency parsing + venv import check + a deps table),
  `workflows/backup_restore.py` (replica venv-package replication step + prompt).
- Docs: `docs/operations/addon-inventory.md`, `docs/operations/instance-management.md`; `CHANGELOG.md`.
- Tests: `tests/test_addons.py` (manifest python-deps parsing).

## Note

Stacked on the scope-db-listing-by-owner change.
