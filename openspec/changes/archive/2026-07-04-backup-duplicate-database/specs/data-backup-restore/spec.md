## ADDED Requirements

### Requirement: Standalone database duplication

The tool SHALL offer a database-only duplication that copies a source database into a target on the **local**
PostgreSQL server, reusing the selectable copy method (fast template copy, or robust
`pg_dump | pg_restore --role` that reassigns ownership), the copied/moved and neutralize migration semantics,
and an optional filestore copy placed under the **current instance's** data directory. It SHALL NOT provision
or modify any instance service, config, or system user. It SHALL validate the source and target database names
as safe, require phrase confirmation, and — when the target database already exists — require an explicit
overwrite before dropping and recreating it.

#### Scenario: A database is duplicated with the chosen method and semantics

- **WHEN** the operator duplicates a database
- **THEN** the plan seeds the target from the source using the selected copy method, applies the copied/moved
  and neutralize semantics, optionally copies the filestore, and runs only after the phrase confirmation

#### Scenario: Existing target database requires an explicit overwrite

- **WHEN** the target database already exists
- **THEN** the tool requires an explicit overwrite confirmation and, only then, drops and recreates it;
  otherwise it cancels without changes

#### Scenario: No instance service or config is touched

- **WHEN** the database duplication runs
- **THEN** only database and (optional) filestore operations are planned — no systemd unit, `odoo.conf`, or
  system user is created or modified
