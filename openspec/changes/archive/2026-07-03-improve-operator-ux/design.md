# Design

## Credential reuse

`DbCredentials(host, port, user, password)` is a frozen dataclass in `workflows/common.py`.
`_ask_db_credentials(default_user, cached=None)` returns the cached credentials when the operator accepts the
reuse prompt (`¿Usar credenciales DB anteriores (user@host:port)?`), otherwise collects fresh values (using
`ask_secret` for the password) and returns them.

The management session threads the credentials explicitly rather than via global state (the review flagged
process-global state as a smell): `manage_existing_instance` holds `db_creds: DbCredentials | None`, and each
of `_backup_instance` / `_restore_backup` / `_duplicate_instance` / `_delete_instance` now takes `cached` and
**returns** the credentials it used (or the unchanged cache on an early cancel). The loop assigns the return
back to `db_creds`, so the next data action offers to reuse them.

`_pick_db_name(creds, label)` replaces `_select_db_name`: it lists databases with the already-collected
credentials and lets the operator pick or type — eliminating the second credential prompt that backup and
duplicate previously issued just to list databases.

## Secret input

`ask_secret(label)` reads via `getpass.getpass`, so passwords are not echoed. It is used only where a password
has **no default** (the operational DB password, the purge admin password). The install/update prompts keep
`ask_text` because they intentionally offer a visible default (the instance name), which `getpass` cannot
show; those are documented as a security consideration in `docs/configuration-reference.md`.

## ask_int / ask_port

`ask_int(label, default, min_value=1, max_value=65535)` keeps the historic port range as the default (so
existing port callers are unaffected) but emits a generic `Valor fuera de rango (min-max)` message.
`ask_port` is the explicit 1–65535 wrapper. `maxretry` (1–1000) and the TLS threshold (1–3650 days) pass their
own bounds, fixing the "Puerto fuera de rango" misfit.

## select_file_path cancel

A `q) Cancelar` entry returns `""`. Callers that require a file (the restore pickers) treat `""` as
"operation cancelled" and return the current credentials. The restore pickers also pass `allowed_extensions`
(`.dump`, `.tar.gz`/`.tgz`) so a wrong file type warns before use.

## Testing

Unit tests (scripted `input`/`getpass` seam): `ask_port` bounds, `ask_int` custom bounds, `ask_secret` no-echo
read, and `_ask_db_credentials` reuse-on-yes / collect-on-no / collect-when-no-cache. The interactive
threading and the file-picker cancel are covered by operator acceptance on a real host.

## Deliberately out of scope

- **Streaming long command output** — changing `system.run`/`apply_commands` to stream would alter the core
  execution path (which captures output for error handling); deferred as higher-risk with lower payoff than the
  credential/secret wins.
- **Masking secrets in the plan preview** — kept as-is: the preview's value is showing the *exact* command
  that will run, and masking it would weaken that transparency. `getpass` already keeps the password off the
  screen at input time.
- **Unifying the three cancel conventions in `choose`** — a broad change to every menu; left for a focused
  follow-up to avoid destabilizing flows that depend on the current empty-string semantics.
