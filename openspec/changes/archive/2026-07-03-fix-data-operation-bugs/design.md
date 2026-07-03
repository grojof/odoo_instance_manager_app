# Design

## Atomic backup + single timestamp

`_backup_instance` computes one `ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")` in Python and uses it
for both the `.dump` and `.filestore.tar.gz` names, so a "DB + Filestore" backup produces a matched pair.

Each artifact is written atomically: dump/tar to `<final>.partial`, then `mv` to the final name only on
success; on failure the partial is removed and the command exits non-zero so `apply_commands` surfaces the
error. `pg_dump` uses `-f "$TMP"` (not shell `>` redirection), so the shell no longer truncates the target
before the dump runs.

The same "one timestamp, one directory" fix applies to `update_existing_configs`, whose per-command
`TS=$(date)` previously scattered config backups across directories.

## psql flags

`_db_admin_psql_command(session, sql, psql_flags="")` inserts `psql_flags` immediately before `-c`. The tuple
(`-tA`) needed for machine-readable listing is now passed explicitly by `_list_instance_databases`, replacing
`.replace("-c", "-tA -c", 1)` — which matched the *first* `-c` anywhere in the string, including inside a
quoted password. Callers that don't pass flags are unchanged.

## Duplication filestore location

`_duplicate_instance` already builds a `target_config = InstanceConfig(instance=target_instance)` for its
existence checks. The target filestore path now resolves from **`target_config`**, so the copy lands under the
target instance's data dir (`/opt/odoo/<target>/.local/share/Odoo/filestore/<target_db>`) instead of the
source's. The source path still resolves from the source `config`.

## Interruption safety

`_execute_install_with_cleanup` catches `(RuntimeError, KeyboardInterrupt)`: both run the residue cleanup, then
the function **returns** (control goes back to the installation menu) rather than re-raising an uncaught
exception that crashed the CLI. The top-level loop in `main()` wraps the menu prompt and the action dispatch:
`KeyboardInterrupt` during an action returns to the menu; `KeyboardInterrupt`/`EOFError` at the menu prompt
exits cleanly with code 0 (no traceback).

## Path-component safety

`_is_safe_path_component(name)` rejects empty, `.`/`..`, names with `/`, `\`, or NUL, and dotfile-style names.
It gates operator-entered database names in `_backup_instance`, `_restore_backup`, and `_delete_instance`
before they are interpolated into a filestore path that is created, archived, or deleted. (The duplication
target is already covered by the identifier validation added in `harden-identifier-validation`.) This is a
targeted traversal guard, deliberately looser than the full PostgreSQL identifier regex so it does not reject
legitimate existing database names.

## ask_bool

`ask_bool` now recognizes `{y, yes, s, si, sí}` as affirmative and `{n, no}` as negative, re-prompts on any
other non-empty input, and keeps Enter → default. This fixes the silent "sí → No" misread on confirmations
such as overwrite prompts.

## Testing

Pure/seam-testable additions: `_is_safe_path_component`, `_db_admin_psql_command` flag insertion (local +
remote, incl. a password containing `-c`), and `ask_bool` parsing (via a scripted-`input` seam). The atomic
shell command strings and the KeyboardInterrupt flow are covered by manual acceptance on a disposable VM.

## Out of scope

Broader UX work (caching DB credentials, `getpass`, unified cancel, streaming output) is the
`improve-operator-ux` change; the `workflows.py` split is `refactor-workflows-module`.
