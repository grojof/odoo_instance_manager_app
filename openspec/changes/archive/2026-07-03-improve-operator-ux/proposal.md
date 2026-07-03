# Improve operator UX

## Why

The diagnostic review flagged the interactive experience as the weakest part of the tool:

- **DB credentials are re-asked constantly** — within a single management session, backup, restore, duplicate,
  and delete each prompt for host/port/user/password from scratch (and backup asked twice: once to list DBs,
  once to dump). This was called the worst friction in the app.
- **Passwords are echoed** to the screen (plain `input()`) and typed in the clear.
- **`ask_int` always reported "Puerto fuera de rango"** even for non-port values like `maxretry`.
- **`select_file_path` had no way to cancel** — once in the picker the only exit was supplying a path (or
  Ctrl+C, which killed the app), and the restore dump/filestore pickers applied no extension filter.

## What changes

- **DB credential reuse per session:** a `DbCredentials` dataclass plus `_ask_db_credentials(default_user,
  cached)` — collected once and threaded through the management session (backup / restore / duplicate /
  delete), offering to reuse the previous credentials. Backup/duplicate list and dump databases with the
  **same** connection instead of prompting twice.
- **Secret input via `getpass`:** a new `ask_secret` reads passwords without echoing them; used for the
  operational DB password and the purge admin password (prompts that have no default).
- **`ask_int` bounds + `ask_port`:** `ask_int` takes `min_value`/`max_value` with a generic out-of-range
  message; `ask_port` wraps the 1–65535 case. `maxretry` and the TLS-expiry threshold now use sensible bounds.
- **`select_file_path` cancel:** a `q) Cancelar` option returns an empty path; the restore pickers pass
  extension filters (`.dump`, `.tar.gz`) and treat cancel as "operation cancelled".

## Impact

- Affected code: `instance_manager/prompts.py`, `instance_manager/workflows/{common,backup_restore,manage,
  purge,fail2ban,report}.py`.
- Affected spec: `execution-safety` gains a "secret input is not echoed" requirement.
- New unit tests for `ask_port`, `ask_secret`, and `_ask_db_credentials` reuse/collect logic.
- The dead `_select_db_name` helper (superseded by `_pick_db_name`) is removed.
- No change to generated commands' content; the plan → preview → apply flow and all phrase confirmations are
  unchanged.
