# Harden the data operations

## Why

An audit of the data operations found ways to lose or expose data that the preview and the confirmation phrase
do not prevent, because the plan shown is itself the wrong plan:

- **Delete instance** removes `/opt/odoo/<instance>`, which holds Odoo's default data dir, so every filestore is
  deleted even when the operator answers "No" to deleting the filestore.
- **Purge** and the database listing select databases by `LIKE '<instance>%'`: purging `shop` drops `shop2`
  and `shop_eu` (and `_` is a LIKE wildcard).
- **Duplicate instance** drops the target database with no check that it is the target's: typing production's
  name drops production. A template copy for a different role produces a database whose tables that role
  cannot use, and the template copy did not block the source's reconnecting sessions (the blocking helper was
  dead code that only the tests called).
- **Scheduled backups** exit 0 when `pg_dump` fails, write dumps world-readable, and their retention glob
  deletes another instance's or another database's dumps. Values were written into the script unquoted.
- **Restore** deletes the current filestore before extracting (with the service running) and leaves the files
  owned by root or another instance's user.
- **Operator values reach a root shell unquoted**: the repo branch, the domain, the app-server IP and database
  names; existence probes run before any preview.

## What changes

- **execution-safety — Identifier validation (MODIFIED):** the Odoo version, repo branch, domain, DB host,
  app-server IP and every database name are validated (Odoo's `DBNAME_PATTERN` for databases); prompts ask
  again on an invalid value; existence probes quote what they receive.
- **instance-removal (MODIFIED):** delete moves a data dir that lives inside the home out to
  `/var/backups/<instance>/kept-data-dir-<timestamp>` before removing the home, and removes the backup timer;
  purge selects databases by owner or exact name only (prefix look-alikes are reported, not selected), drops
  the role the operator named, and removes the backup timer and the fail2ban jail.
- **data-backup-restore (MODIFIED):** backups are named `<instance>--<db>--<timestamp>` and are private;
  restore moves an existing filestore aside and hands the data dir to the instance user; duplication refuses a
  target database of another role, the source database or instance as target, and a template copy across
  roles; the template copy blocks and always reopens the source; drops use `dropdb --force`; the confirmation
  phrase is `DUPLICATE <instance>`.
- **scheduled-backups (MODIFIED):** the script fails on a failed or unreadable dump, a missing filestore or a
  failed archive, leaves no partial file, writes private files, and prunes per database.
- **disk-usage (MODIFIED):** retention keeps N per database and kind.
- **instance-configuration (MODIFIED):** the management database listing is scoped to the role's databases
  and the database named like it, without a prefix match.

## Impact

- Code: `models.py`, `prompts.py`, `system.py`, `planners.py`, `workflows/{backup_restore,common,manage,purge,
  scheduled_backup,diskusage,install}.py`, `i18n.py`.
- Tests: updated and new unit tests; `tools/verify_data_safety.py` executes the generated script, retention,
  the delete step, the template copy, the forced drop and the purge discovery (stubs + a throwaway PostgreSQL).
- Behaviour visible to operators: new backup file names (old ones are still pruned, as their own group);
  `DUPLICATE` replaces `DUPLICAR`; PostgreSQL 13+ for local drops (every supported distribution ships newer).
- Not in this change: neutralising copies completely (a later change), `update existing configuration`.
