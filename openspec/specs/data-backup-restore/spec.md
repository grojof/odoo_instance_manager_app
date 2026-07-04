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

The tool SHALL duplicate a source database into a new target using PostgreSQL template copy, refusing to
overwrite an existing target instance, service, database, or filestore, and require phrase confirmation.
Because a template copy requires no other sessions on the source database, the tool SHALL prepare the source
for the copy without the operator stopping the service: block new connections to the source, terminate its
existing sessions, run the template copy, and **re-enable connections to the source afterward even if the copy
fails**. It SHALL operate with the instance's own database role (no superuser assumed) and validate the source
database name as safe before using it in SQL. The duplicated filestore SHALL be placed under the **target**
instance's data directory. Duplication copies the database and (optionally) the filestore only; it does **not**
provision the target instance's service, config, or system user.

#### Scenario: Pre-existing target resources block duplication

- **WHEN** the target home, systemd service, database, or (when duplicating the filestore) target filestore
  already exists
- **THEN** the operation reports the specific conflict and stops without executing

#### Scenario: Duplication frees the source, copies via template, and is phrase-confirmed

- **WHEN** the duplication plan is assembled
- **THEN** it blocks new connections to the source database, terminates its existing sessions, creates the
  target with `createdb -T <source>` (optionally copying the filestore), and runs only after the operator types
  the exact `DUPLICAR <instance>` phrase

#### Scenario: Source connections are re-enabled even if the copy fails

- **WHEN** the template-copy step fails after the source was blocked
- **THEN** the plan re-enables connections to the source database regardless, leaving the source reachable

#### Scenario: Unsafe source database name is rejected

- **WHEN** the source database name is not a safe name
- **THEN** the plan is not built and the operation reports the problem instead of interpolating it into SQL

#### Scenario: Duplicated filestore lands under the target instance

- **WHEN** the filestore is duplicated
- **THEN** the copy is written under the target instance's data directory (resolved from the target instance),
  not the source instance's, so the duplicated instance has its attachments

#### Scenario: Duplication does not provision the target instance

- **WHEN** duplication completes
- **THEN** only the database and (optionally) filestore exist for the target; provisioning its service, config,
  and user remains a separate install step

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

