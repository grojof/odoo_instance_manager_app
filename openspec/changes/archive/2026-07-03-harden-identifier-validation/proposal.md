# Harden identifier validation on destructive flows

## Why

The `execution-safety` capability requires that instance and PostgreSQL identifiers are validated **before
they are used to build any command or configuration**. The provisioning flows honor this (they loop on
`validate_identifiers()` until it passes), but the **removal, purge, and duplication** flows do not: an
instance name typed through `_select_existing_instance` reaches raw root shell commands and raw SQL unquoted.

This is a critical, root-level vulnerability:

- **Shell injection** — the name is interpolated unquoted into `rm -f /etc/systemd/system/<service>.service`,
  Nginx vhost removals, and log deletions (`workflows.py:1610,1619,1623` in `_delete_instance`;
  `:1812,1825,1829` in `purge_instance_superuser`). A name like `x;reboot #` runs `reboot` as root; a name
  with a space deletes the wrong files.
- **SQL injection** — the name is interpolated into `DROP ROLE IF EXISTS {role};` (`workflows.py:1868`)
  without `_sql_literal` or identifier quoting. A name like `x; DROP DATABASE prod; --` executes an unrelated
  `DROP DATABASE` as the postgres superuser.

The `_duplicate_instance` target instance/DB name (`workflows.py:1502-1503`) is likewise unvalidated before it
is used to build paths and commands.

## What changes

- Validate the selected/typed instance identifier as early as possible in `manage_existing_instance`,
  `_delete_instance`, `purge_instance_superuser`, and the `_duplicate_instance` target, rejecting names that
  fail `INSTANCE_NAME_RE` (and DB names that fail `POSTGRES_IDENTIFIER_RE`) before any command or SQL is built.
- Quote path interpolations in the removal/purge command builders as defense in depth.
- Strengthen the `execution-safety` spec with explicit scenarios asserting that manually-selected instances,
  duplication targets, and the purge flow are validated before any plan is built.
- Add unit tests covering `validate_identifiers()` rejection and the guard on these flows.

Behavior for valid inputs is unchanged; the flows simply refuse unsafe names instead of executing them.

## Impact

- Affected spec: `execution-safety` (strengthened, no requirement removed).
- Affected code: `instance_manager/workflows.py` (removal, purge, duplication, management entry), with a small
  helper for early validation; `instance_manager/models.py` unchanged (validators already exist).
- No change to the provisioning or audit flows.
