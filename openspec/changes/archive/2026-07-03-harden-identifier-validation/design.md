# Design

## Approach

The `InstanceConfig.validate_identifiers()` validator already exists and is the single source of truth for
safe identifiers (`INSTANCE_NAME_RE`, `POSTGRES_IDENTIFIER_RE` in `models.py`). The fix is to **call it at the
entry of every destructive flow**, and to quote path interpolations as defense in depth. No new validation
logic is introduced.

## Validation seam

Add a small helper in `workflows.py`:

```python
def _validate_instance_or_abort(instance: str) -> InstanceConfig | None:
    config = InstanceConfig(instance=instance)
    config.normalize_defaults()
    try:
        config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return None
    return config
```

Wire it in:

- `manage_existing_instance` (`workflows.py:1904`) — validate right after `_select_existing_instance`; abort
  to menu on failure. This transitively protects `_delete_instance` (reached only from here).
- `purge_instance_superuser` (`workflows.py:1757`) — validate the selected instance before building any SQL or
  cleanup command; abort on failure.
- `_duplicate_instance` (`workflows.py:1494`) — validate the **target** instance and target DB name (build an
  `InstanceConfig(instance=target_instance)` with `db_user=target_db`) before assembling the plan; abort on
  failure. This also fixes the pre-existing habit of constructing the target config only for existence checks.

`_delete_instance` receives an already-validated `config` from `manage_existing_instance`, so no separate
prompt path remains unvalidated. `update_existing_configs` is already protected transitively (its
`plan_odoo_base_setup` validates and raises before any command runs), but validating early gives a cleaner
error.

## Defense in depth: quoting

Even with validation, quote path interpolations in the residue-cleanup command builders
(`_build_partial_install_cleanup`, `_delete_instance`, `purge_instance_superuser`) using `_quote()` for the
Nginx vhost, unit-file, and log paths that are currently bare f-strings. Validation makes injection
impossible for the *instance* token; quoting is the belt-and-suspenders and also guards future edits.

## Why not validate inside `_delete_instance` / cleanup builders directly

Validation belongs at the **input boundary** (where the operator supplies the name), not deep in a plan
builder — a builder should be able to assume its `InstanceConfig` is already valid (as the provisioning path
guarantees). Centralizing the check at flow entry keeps the invariant "a plan is built only from a validated
config" clear and testable.

## Testing

- `test_validate_identifiers_rejects_bad_names` — parametrized over `"1bad"`, `"Bad"`, `"a"*33`,
  `"x;reboot"`, `"con-guion"` (raise) and `"odoo18"`, `"a_b"` (pass).
- `test_validate_instance_or_abort_returns_none_on_bad_name` — the helper returns `None` (no exception
  escapes) for an unsafe name and a config for a safe one.
- These run with zero mocking (pure `models.py` + the helper), matching the stdlib-only runtime.

## Out of scope

Broader path-traversal hardening on free-typed DB/filestore names (e.g. `store_db=".."`) and the atomic-dump
and timestamp bugs are tracked separately in the `fix-data-operation-bugs` change; this change is limited to
identifier validation on the destructive flows.
