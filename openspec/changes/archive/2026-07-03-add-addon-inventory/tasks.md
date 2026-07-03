# Tasks

- [x] 1.1 Add `workflows/addons.py`: roots discovery, origin classification, module+version listing (regex),
  optional installed-state from `ir_module_module`, grouped tables.
- [x] 1.2 Wire "Inventario de addons" into `manage_existing_instance`.
- [x] 2.1 Add the `addon-inventory` spec.
- [x] 2.2 Add `tests/test_addons.py` (version parse, classification, module listing).
- [x] 2.3 Add `docs/addon-inventory.md`, linked from the README and instance-management page.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a VM: view the inventory and, with a DB, confirm installed modules/versions are marked.
