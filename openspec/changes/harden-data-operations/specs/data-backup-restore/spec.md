## MODIFIED Requirements

### Requirement: Backup

The tool SHALL back up an instance's database (as a compressed custom-format dump) and/or its filestore (as a
gzipped tar) into the chosen backup directory, using a **single timestamp for the whole operation**, naming
each artifact `<instance>--<db>--<timestamp>`, and writing each artifact **atomically** (a temporary file
promoted only on success). The backup directory SHALL be private to root (`700`) and every artifact SHALL be
written private (`umask 077`): a dump holds password hashes, API keys and mail/payment secrets.

#### Scenario: Database backup produces an atomic timestamped custom dump

- **WHEN** the operator selects a backup that includes the database
- **THEN** the plan runs `pg_dump -Fc` to a temporary file and renames it to
  `<backup_dir>/<instance>--<db>--<timestamp>.dump` only on success, removing the temporary file and failing
  the step otherwise

#### Scenario: Filestore backup archives the resolved filestore path atomically

- **WHEN** the operator selects a backup that includes the filestore
- **THEN** the plan tars the resolved filestore directory to a temporary file and renames it to
  `<backup_dir>/<instance>--<db>--<timestamp>.filestore.tar.gz` only on success; a file that changed while
  being read (GNU tar exit 1) does not fail the archive, any other tar failure does

#### Scenario: DB dump and filestore archive share one timestamp

- **WHEN** the operator selects a "DB + Filestore" backup
- **THEN** the `.dump` and `.filestore.tar.gz` names carry the **same** timestamp so the pair can be matched

#### Scenario: Backups are private

- **WHEN** a backup is written
- **THEN** the backup directory is mode `700` and the artifacts are readable by root only

### Requirement: Restore

Restoring SHALL create the target database from a selected dump and/or restore a filestore archive, refusing to
clobber an existing target database, and require phrase confirmation before applying. The pre-restore
existence check for the target database is evaluated against the **local** PostgreSQL server. An existing
target filestore SHALL be moved aside, never deleted, and the restored files SHALL belong to the instance user.

#### Scenario: Existing target database blocks restore

- **WHEN** the restore includes the database and the target database already exists
- **THEN** the operation reports the conflict and stops without executing

#### Scenario: Target-database existence check is local-only

- **WHEN** the operator targets a remote database host for the restore
- **THEN** the pre-restore existence check runs against the local server and may not detect a remote
  collision; the subsequent `createdb` still fails safely if the remote target exists

#### Scenario: Existing target filestore requires explicit overwrite

- **WHEN** the restore includes the filestore and the target filestore exists
- **THEN** the operator must confirm overwrite; on confirmation the previous filestore is moved to
  `<filestore>.replaced-<timestamp>` before extracting, otherwise the restore is cancelled

#### Scenario: Restored files belong to the instance user

- **WHEN** a filestore archive is extracted
- **THEN** tar does not restore the archive's owners (`--no-same-owner`) and the plan chowns the instance's data
  dir to the instance user, so Odoo can write attachments and sessions

#### Scenario: Restore is phrase-confirmed

- **WHEN** the restore plan is assembled
- **THEN** it executes only after the operator types the exact `RESTORE <instance>` phrase

### Requirement: Duplication

The tool SHALL duplicate a source instance's database — and optionally its filestore — into a target,
end-to-end and existence-aware, requiring phrase confirmation and validating the source and target database
names as safe before using them in SQL. The target instance SHALL differ from the source instance, and the
target database SHALL differ from the source database.

The operator SHALL choose the database copy method: a fast PostgreSQL **template** copy, or a robust
**`pg_dump | pg_restore --no-owner`** that reassigns ownership to the target role. A template copy keeps the
source's role as owner of every table, so the tool SHALL refuse it when the target role differs from the source
database's owner (always the case for a new replica). The template copy SHALL refuse new connections to the
source, terminate its sessions, copy, and reopen the source whatever the outcome.

When the **target instance does not exist**, duplication SHALL provision it fully before seeding: create the
target role, run the base setup (system user, home, Odoo checkout at the source's version, virtualenv,
`odoo.conf`, systemd unit) **without starting the service**, optionally configure Nginx, seed the database and
filestore, then start the service. The replica SHALL follow the **same production-hardening prompts as a fresh
install** (secrets with informed choice, `list_db`, `dbfilter`, worker sizing, `db_sslmode`, wkhtmltopdf) with
auto-suggested non-colliding internal ports, and — when it fronts Nginx — SHALL require a domain that is **not
already served by another vhost** (or the replica would be unreachable behind a shared `server_name`). It SHALL
also offer to **replicate the source venv's Python packages** into the target venv, so addon dependencies the
source installed beyond `requirements.txt` are present in the replica.

When the **target instance already exists**, duplication SHALL refresh it in place: stop the target service,
drop and recreate its database from the source and replace its filestore, apply the migration semantics, and
restart — **without** recreating the target's config, service, or system user. It SHALL drop an existing
target database only when that database belongs to the target's own role (read from its `odoo.conf`) and the
operator explicitly confirms the overwrite.

Migration semantics (copied vs moved, neutralize) SHALL apply in both cases, and the duplicated filestore SHALL
be placed under the **target** instance's data directory, which SHALL be owned by the target system user (so
Odoo can create its `sessions`/`filestore` entries). Every database the tool seeds SHALL have its access
**restricted to its owner** — `CONNECT` revoked from `PUBLIC` and granted to the owning role — so an instance's
database role cannot reach other instances' databases. Local drops SHALL use `dropdb --force`, which closes the
database's sessions and refuses new ones in one statement.

#### Scenario: Replica replicates the source venv Python packages

- **WHEN** a replica is provisioned and the operator opts to replicate packages
- **THEN** the plan installs the source venv's packages (a filtered `pip freeze`) into the target venv, so the
  replica has the same addon Python dependencies as the source

#### Scenario: New target is provisioned and seeded as a replica

- **WHEN** the target instance does not exist
- **THEN** the plan creates the target role, runs the same production-hardening prompts as a fresh install with
  auto-suggested non-colliding ports, provisions the target (base setup without starting, optional Nginx),
  seeds the database and filestore from the source with the `pg_dump` copy, and then starts the target service

#### Scenario: Replica domain must not collide with another vhost

- **WHEN** the replica is configured to front Nginx and the chosen domain is already a `server_name` in an
  enabled vhost
- **THEN** the tool rejects it and re-prompts for a different domain, so the replica is reachable

#### Scenario: Existing target is refreshed in place

- **WHEN** the target instance already exists
- **THEN** the plan stops the target service, drops and recreates its database from the source, replaces its
  filestore, applies the migration semantics, and restarts the service without recreating its config or unit

#### Scenario: A database that is not the target's is never dropped

- **WHEN** the target database exists and belongs to a role other than the target's, or the target equals the
  source instance or the source database
- **THEN** the tool refuses with a descriptive error and builds no plan

#### Scenario: Overwriting the target's database is confirmed

- **WHEN** the target database exists and belongs to the target's role
- **THEN** the operator must explicitly confirm that it will be dropped and replaced before the plan is built

#### Scenario: Operator selects the database copy method

- **WHEN** the duplication plan is assembled
- **THEN** the operator chooses a template copy or a `pg_dump | pg_restore --no-owner` copy, and the plan uses
  the selected method, refusing a template copy across roles

#### Scenario: Template copy frees the source; dump copy leaves it untouched

- **WHEN** the template method is chosen
- **THEN** the plan blocks and terminates the source's sessions before the copy and re-enables them afterward
  even on failure; **WHEN** the dump method is chosen, the source is read live without terminating its sessions

#### Scenario: Migration semantics and phrase confirmation

- **WHEN** duplication runs
- **THEN** copied/moved and neutralize semantics are applied to the target and execution proceeds only after
  the operator types the exact `DUPLICATE <instance>` phrase

#### Scenario: Seeded database is restricted to its owner

- **WHEN** the tool seeds a target database
- **THEN** the plan revokes `CONNECT` on that database from `PUBLIC` and grants it to the owning role, so other
  instances' roles cannot connect to it

#### Scenario: Target data dir is owned by the target user

- **WHEN** the filestore is copied into the target data directory (created as root)
- **THEN** the plan chowns the whole target data directory to the target system user, so Odoo can create its
  `sessions` and `filestore` entries

#### Scenario: Unsafe database name is rejected

- **WHEN** the source or target database name is not a safe name
- **THEN** the plan is not built and the operation reports the problem instead of interpolating it into SQL

### Requirement: Database name path safety

An operator-entered database name SHALL be a name Odoo's own database manager accepts
(`^[a-zA-Z0-9][a-zA-Z0-9_.-]+$`, at most 63 characters) before it is interpolated into SQL, a shell command or a
filestore path that is created, archived, or deleted. Such a name holds no path separator, quote, `$` or space,
and cannot start with `-` (an option to `createdb`/`dropdb`/`pg_dump`) or `.`.

#### Scenario: Traversal in a database name is refused

- **WHEN** a database name used for backup, restore, scheduled backup, or filestore deletion contains a path
  separator, starts with `.` or `-`, or holds any character outside Odoo's pattern
- **THEN** the operation is refused with a descriptive error and no command is built or executed

### Requirement: Standalone database duplication

The tool SHALL offer a database-only duplication that copies a source database into a target on the **local**
PostgreSQL server, reusing the selectable copy method (fast template copy, or robust
`pg_dump | pg_restore --role` that reassigns ownership), the copied/moved and neutralize migration semantics,
and an optional filestore copy placed under the **current instance's** data directory. It SHALL NOT provision
or modify any instance service, config, or system user. It SHALL validate the source and target database names
as safe, require phrase confirmation, refuse a target database owned by another role than the instance's and a
template copy across roles, and — when the target database already exists — require an explicit overwrite
before dropping and recreating it.

#### Scenario: A database is duplicated with the chosen method and semantics

- **WHEN** the operator duplicates a database
- **THEN** the plan seeds the target from the source using the selected copy method, applies the copied/moved
  and neutralize semantics, optionally copies the filestore, and runs only after the phrase confirmation

#### Scenario: Existing target database requires an explicit overwrite

- **WHEN** the target database already exists and belongs to the instance's role
- **THEN** the tool requires an explicit overwrite confirmation and, only then, drops and recreates it;
  otherwise it cancels without changes

#### Scenario: Another role's database is not overwritten

- **WHEN** the target database exists and belongs to another role
- **THEN** the tool refuses with a descriptive error and builds no plan

#### Scenario: No instance service or config is touched

- **WHEN** the database duplication runs
- **THEN** only database and (optional) filestore operations are planned — no systemd unit, `odoo.conf`, or
  system user is created or modified
