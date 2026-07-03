# Refactor the workflows module (phased)

## Why

`instance_manager/workflows.py` is a ~3000-line god-module mixing eight capabilities, with duplicated helpers,
dead code, and stringly-typed data passed by position. It is hard to navigate and review, and it is the one
file every change touches. Now that a test suite and CI gate exist, it can be split safely into a package by
capability, with duplication and dead code removed.

## What changes

Pure refactor — **no behavior change, no spec delta**. Delivered in phases, each its own green PR:

- **Phase 1 — housekeeping:** remove dead code (`_truncate_text`, `_list_odoo_conf_instances`,
  `_discover_odoo_conf_paths` in `workflows.py`; `group_exists`, `print_status_line` in `system.py`;
  `status_tag` in `ui.py`) and consolidate the duplicated `_sql_literal` / `_is_local_db_host` (keep the
  `planners.py` copies, import them in `workflows.py`).
- **Phase 2 — package + `common.py`:** turn `workflows.py` into a `workflows/` package; move the shared,
  low-level helpers (plan execution, instance/DB selection, filestore path, validation) into
  `workflows/common.py`; `__init__` re-exports the public entry points.
- **Phase 3 — `report.py`:** extract the ~1000-line external-report cluster; replace its 27-field positional
  rows with a dataclass.
- **Phase 4 — `fail2ban.py`** and **`services.py`.**
- **Phase 5 — `backup_restore.py`** and **`purge.py`** (with a `DbAdminSession` dataclass).
- **Phase 6 — `install.py`** and **`manage.py`**, leaving `__init__` a thin re-export.

Each phase keeps the public API (`odoo_instance_manager.py` imports) and the tests green, and preserves
`preview → confirm → apply` and every phrase confirmation exactly.

## Impact

- Affected code: `instance_manager/workflows.py` → `instance_manager/workflows/` package; small edits to
  `system.py`, `ui.py`, and test imports as helpers move.
- No spec delta (behavior unchanged). CI (`ruff`, `pytest`, `openspec validate`, doc checks) gates every phase.
- Enables tightening `E501` on the new, smaller modules in a later pass.
