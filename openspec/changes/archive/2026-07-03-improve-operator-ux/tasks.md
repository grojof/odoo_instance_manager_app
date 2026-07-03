# Tasks

## 1. Prompt primitives

- [x] 1.1 `ask_int(label, default, min_value=1, max_value=65535)` with a generic out-of-range message; add
  `ask_port`; point `maxretry` and the TLS threshold at explicit bounds.
- [x] 1.2 Add `ask_secret` (getpass, no echo).
- [x] 1.3 `select_file_path`: add a `q) Cancelar` option returning `""`.

## 2. Credential reuse

- [x] 2.1 Add `DbCredentials` dataclass, `_ask_db_credentials`, and `_pick_db_name` to `common.py`; remove the
  superseded `_select_db_name`.
- [x] 2.2 Thread cached credentials through `_backup_instance` / `_restore_backup` / `_duplicate_instance`
  (backup_restore.py) and `_delete_instance` (manage.py); each returns the credentials used.
- [x] 2.3 `manage_existing_instance` holds a session `db_creds` and threads it through the four data actions.

## 3. Secret input

- [x] 3.1 Use `ask_secret` for the operational DB password (`_collect_db_connection`) and the purge admin
  password; leave defaulted install/update prompts on `ask_text`.

## 4. File picker

- [x] 4.1 Restore pickers pass extension filters (`.dump`, `.tar.gz`) and treat cancel as "operation
  cancelled".

## 5. Spec + tests

- [x] 5.1 `execution-safety`: add the "secret input is not echoed" requirement.
- [x] 5.2 Add `tests/test_ux_helpers.py` (ask_port bounds, ask_secret, `_ask_db_credentials` reuse/collect).

## 6. Verify

- [x] 6.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 6.2 (operator) On a disposable VM: confirm credentials are collected once per management session and
  reused, passwords are not echoed, and the file picker can be cancelled.
