# Tasks

## 1. Validation seam

- [x] 1.1 Add `_validate_instance_or_abort(instance: str) -> InstanceConfig | None` helper in `workflows.py`
  (build config, `normalize_defaults`, `validate_identifiers`, print error + return `None` on failure).

## 2. Wire into destructive flows

- [x] 2.1 `manage_existing_instance`: after `_select_existing_instance`, validate via the helper; return to
  menu on failure. Use the returned validated config.
- [x] 2.2 `purge_instance_superuser`: validate the selected instance before building any SQL or cleanup
  command; abort on failure.
- [x] 2.3 `_duplicate_instance`: validate the target instance and target DB name (against instance /
  PostgreSQL patterns) before assembling the plan; abort on failure.
- [x] 2.4 Confirm `_delete_instance` only ever receives an already-validated config (reached solely from
  `manage_existing_instance`); no separate change needed beyond 2.1.

## 3. Defense in depth: quoting

- [x] 3.1 Quote path interpolations (`_quote()`) for unit-file, Nginx vhost, and log paths in
  `_build_partial_install_cleanup`, `_delete_instance`, and `purge_instance_superuser`.

## 4. Tests

- [x] 4.1 Add `tests/test_models.py::test_validate_identifiers_rejects_bad_names` (parametrized reject/accept).
- [x] 4.2 Add `tests/test_workflows_validation.py::test_validate_instance_or_abort` (None on bad name, config
  on good name).

## 5. Verify

- [x] 5.1 `openspec validate --specs` and `openspec validate --change harden-identifier-validation` pass.
- [ ] 5.2 (operator) Manually drive the delete and purge menus with a crafted name (e.g. `x;reboot #`) on a
  disposable VM and confirm the flow refuses it before building a plan. Covered in principle by the unit tests
  in 4.1/4.2; left for operator acceptance on a real host.
