# Design

## Invariants held across every phase

- **Public API unchanged.** `odoo_instance_manager.py` imports eight entry functions from
  `instance_manager.workflows`; every phase keeps those importable from that path (re-exported by the package
  `__init__`).
- **Behavior unchanged.** No emitted command, prompt, or confirmation phrase changes. `preview → confirm →
  apply` and `confirm_with_phrase` stay exactly as they are.
- **Green at every phase.** `ruff`, `pytest`, `openspec validate --specs`, `docs-check`, `provenance-check`
  pass on each PR before merge.
- **Tests follow the code.** When a function under test moves modules, its test import is updated in the same
  phase (no re-export gymnastics just to keep tests pinned to the old path).

## Phase 1 (this PR): housekeeping, no moves

Purely subtractive plus one import consolidation, so the diff is easy to review:

- Remove dead functions verified to have zero call sites: `workflows._truncate_text`,
  `workflows._list_odoo_conf_instances`, `workflows._discover_odoo_conf_paths`, `system.group_exists`,
  `system.print_status_line`. Removing `print_status_line` makes `ui.status_tag` unused, so drop it and its
  import in `system.py`.
- The `_sql_literal` and `_is_local_db_host` bodies are byte-identical in `planners.py` and `workflows.py`.
  Keep the `planners.py` copies (the lower layer) and import them into `workflows.py`, deleting the local
  duplicates.

## Later phases: the split (dependency-safe order)

The package is built bottom-up so submodules only ever import from `common` (and standard lower layers
`models`/`planners`/`system`/`prompts`/`ui`), never from each other or from `__init__` — no import cycles:

```
workflows/
  __init__.py        # re-exports the 8 public entry functions
  common.py          # _execute_plan, _quote, selection/probe helpers, _filestore_path,
                     # _validate_instance_or_abort, _is_safe_path_component, _command_output, …
  report.py          # external_server_report + discovery/parse cluster (InstanceReportRow dataclass)
  fail2ban.py        # manage_fail2ban + jail/IP helpers
  services.py        # manage_instance_services
  backup_restore.py  # _backup_instance/_restore_backup/_duplicate_instance + _post_db_mode_commands
  purge.py           # purge_instance_superuser + DbAdminSession dataclass
  install.py         # install_* + port suggestion + cleanup
  manage.py          # manage_existing_instance + status/update/repair/venv/delete
```

Extraction order (each a PR): common → report → fail2ban/services → backup_restore/purge → install/manage.
`report.py` goes early because it is the largest and most self-contained slice.

## Typing cleanups folded into the relevant phase

- `report.py`: replace the 27-field positional row lists (`row[0]`…`row[26]`) with an `InstanceReportRow`
  dataclass and explicit table projections.
- `purge.py`: replace the positional `tuple[str,str,int,str,str]` admin session with a `DbAdminSession`
  dataclass.

These are done as part of extracting each module, not as separate churn.

## Why phased rather than one big move

A single 3000-line move is unreviewable and risks a silent behavioral change in a root-run tool. Small,
green, capability-sized PRs keep each diff legible and each step reversible.
