# Fix data-operation bugs

## Why

The diagnostic review found a cluster of correctness bugs in the data and install flows that can lose or
corrupt data, or leave the host in a bad state:

- **Duplication placed the copied filestore under the *source* instance's data dir**, so the duplicated
  instance started without its attachments.
- **`pg_dump > file.dump`** truncated the target before dumping, leaving a 0-byte/partial `.dump` on failure
  that could later be "restored" as an empty database.
- **Backup DB dump and filestore archive received independent timestamps** (`TS=$(date)` per command), so the
  pair of files could not be matched; config pre-update backups scattered across directories the same way.
- **`_list_instance_databases` rewrote the psql command via `.replace("-c", "-tA -c", 1)`**, which corrupts
  the command when the password/host contains `-c`, silently under-detecting databases during purge.
- **Ctrl+C during an install bypassed the automatic cleanup** (only `RuntimeError` was caught), leaving the
  residues the tool exists to clean; and the post-cleanup `raise` crashed the CLI with a traceback.
- **Operator-entered database names flowed unquoted-for-traversal into filestore paths** (`store_db=".."` →
  `rm -rf …/filestore/..` deletes the parent).
- **`ask_bool` silently treated the accented Spanish "sí" as "no"** and did not re-prompt on garbage.

## What changes

- Duplication resolves the target filestore under the **target** instance's data dir.
- Backup dumps atomically (dump to a `.partial`, `mv` on success; clean up on failure), and the DB dump +
  filestore archive share **one** Python-computed timestamp; the same single-timestamp fix is applied to the
  config pre-update backup.
- `_db_admin_psql_command` gains a `psql_flags` parameter; the fragile `.replace` is removed.
- Install failures **and** `KeyboardInterrupt` both trigger cleanup, after which control returns to the menu
  instead of crashing; the top-level menu loop handles `KeyboardInterrupt`/`EOFError` cleanly.
- Operator-entered database names are validated with `_is_safe_path_component` before they are embedded in a
  filestore path that is created, archived, or deleted.
- `ask_bool` accepts `sí`/`s`/`y`/`yes` and `no`/`n`, and re-prompts on unrecognized input (Enter still uses
  the default).

## Impact

- Affected specs: `data-backup-restore` (backup atomicity + timestamp, duplication filestore location, name
  safety) and `execution-safety` (cleanup on interruption + return to menu).
- Affected code: `instance_manager/workflows.py`, `instance_manager/prompts.py`,
  `odoo_instance_manager.py`.
- New unit tests: `_is_safe_path_component`, `_db_admin_psql_command` flags, and `ask_bool` parsing.
- No change to the provisioning command content or the audit flow.
