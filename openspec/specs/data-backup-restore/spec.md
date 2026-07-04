# data-backup-restore Specification

## Purpose

Move instance data safely: back up an instance's database and/or filestore,
restore a dump and/or filestore into a target, and duplicate an instance's
database (and optionally filestore) from a template. Data operations honor
Odoo's copied-vs-moved semantics (UUID regeneration) and optional neutralization
of the target.
## Requirements
### Requirement: Backup

The tool SHALL back up an instance's database (as a compressed custom-format dump) and/or its filestore (as a
gzipped tar) into the chosen backup directory, using a **single timestamp for the whole operation** and
writing each artifact **atomically** (a temporary file promoted only on success).

#### Scenario: Database backup produces an atomic timestamped custom dump

- **WHEN** the operator selects a backup that includes the database
- **THEN** the plan runs `pg_dump -Fc` to a temporary file and renames it to
  `<backup_dir>/<instance>_<timestamp>.dump` only on success, removing the temporary file and failing the step
  otherwise

#### Scenario: Filestore backup archives the resolved filestore path atomically

- **WHEN** the operator selects a backup that includes the filestore
- **THEN** the plan tars the resolved filestore directory to a temporary file and renames it to
  `<backup_dir>/<instance>_<timestamp>.filestore.tar.gz` only on success

#### Scenario: DB dump and filestore archive share one timestamp

- **WHEN** the operator selects a "DB + Filestore" backup
- **THEN** the `.dump` and `.filestore.tar.gz` names carry the **same** timestamp so the pair can be matched

### Requirement: Restore

Restoring SHALL create the target database from a selected dump and/or restore a filestore archive, refusing to
clobber an existing target database, and require phrase confirmation before applying. The pre-restore
existence check for the target database is evaluated against the **local** PostgreSQL server.

#### Scenario: Existing target database blocks restore

- **WHEN** the restore includes the database and the target database already exists
- **THEN** the operation reports the conflict and stops without executing

#### Scenario: Target-database existence check is local-only

- **WHEN** the operator targets a remote database host for the restore
- **THEN** the pre-restore existence check runs against the local server and may not detect a remote
  collision; the subsequent `createdb` still fails safely if the remote target exists

#### Scenario: Existing target filestore requires explicit overwrite

- **WHEN** the restore includes the filestore and the target filestore exists
- **THEN** the operator must confirm overwrite; on confirmation the previous filestore contents are cleared
  before extracting, otherwise the restore is cancelled

#### Scenario: Restore is phrase-confirmed

- **WHEN** the restore plan is assembled
- **THEN** it executes only after the operator types the exact `RESTORE <instance>` phrase

### Requirement: Duplication

The tool SHALL duplicate a source instance's database — and optionally its filestore — into a target,
end-to-end and existence-aware, requiring phrase confirmation and validating the source and target database
names as safe before using them in SQL.

The operator SHALL choose the database copy method: a fast PostgreSQL **template** copy (frees the source of
sessions first, best when the target uses the same role), or a robust **`pg_dump | pg_restore --no-owner`**
that reassigns ownership to the target role (correct for a cross-user target such as production→development).

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
restart — **without** recreating the target's config, service, or system user.

Migration semantics (copied vs moved, neutralize) SHALL apply in both cases, and the duplicated filestore SHALL
be placed under the **target** instance's data directory, which SHALL be owned by the target system user (so
Odoo can create its `sessions`/`filestore` entries). Every database the tool seeds SHALL have its access
**restricted to its owner** — `CONNECT` revoked from `PUBLIC` and granted to the owning role — so an instance's
database role cannot reach other instances' databases.

#### Scenario: Replica replicates the source venv Python packages

- **WHEN** a replica is provisioned and the operator opts to replicate packages
- **THEN** the plan installs the source venv's packages (a filtered `pip freeze`) into the target venv, so the
  replica has the same addon Python dependencies as the source

#### Scenario: New target is provisioned and seeded as a replica

- **WHEN** the target instance does not exist
- **THEN** the plan creates the target role, runs the same production-hardening prompts as a fresh install with
  auto-suggested non-colliding ports, provisions the target (base setup without starting, optional Nginx),
  seeds the database and filestore from the source, and then starts the target service

#### Scenario: Replica domain must not collide with another vhost

- **WHEN** the replica is configured to front Nginx and the chosen domain is already a `server_name` in an
  enabled vhost
- **THEN** the tool rejects it and re-prompts for a different domain, so the replica is reachable

#### Scenario: Existing target is refreshed in place

- **WHEN** the target instance already exists
- **THEN** the plan stops the target service, drops and recreates its database from the source, replaces its
  filestore, applies the migration semantics, and restarts the service without recreating its config or unit

#### Scenario: Operator selects the database copy method

- **WHEN** the duplication plan is assembled
- **THEN** the operator chooses a template copy or a `pg_dump | pg_restore --no-owner` copy, and the plan uses
  the selected method

#### Scenario: Template copy frees the source; dump copy leaves it untouched

- **WHEN** the template method is chosen
- **THEN** the plan blocks and terminates the source's sessions before the copy and re-enables them afterward
  even on failure; **WHEN** the dump method is chosen, the source is read live without terminating its sessions

#### Scenario: Migration semantics and phrase confirmation

- **WHEN** duplication runs
- **THEN** copied/moved and neutralize semantics are applied to the target and execution proceeds only after
  the operator types the exact `DUPLICAR <instance>` phrase

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

### Requirement: Copied vs moved database semantics

Restore and duplication SHALL apply Odoo migration semantics: in "copied" mode
regenerate the target's `database.uuid`; when neutralization is requested,
deactivate crons, outgoing mail servers, and fetchmail servers in the target.

#### Scenario: Copied mode regenerates the database UUID

- **WHEN** the operator selects the copied mode
- **THEN** the plan upserts a fresh `database.uuid` into `ir_config_parameter` on the target database

#### Scenario: Neutralization deactivates automation in the target

- **WHEN** the operator opts to neutralize the target
- **THEN** the plan deactivates `ir_cron`, `ir_mail_server`, and `fetchmail_server` rows (tolerating tables that do not exist)

### Requirement: Database name path safety

An operator-entered database name SHALL be validated as a safe single path component before it is interpolated
into a filestore path that is created, archived, or deleted.

#### Scenario: Traversal in a database name is refused

- **WHEN** a database name used for backup, restore, or filestore deletion contains a path separator or a
  `.`/`..` traversal component
- **THEN** the operation is refused with a descriptive error and no filestore command is built or executed

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

