# data-backup-restore Specification

## Purpose

Move instance data safely: back up an instance's database and/or filestore,
restore a dump and/or filestore into a target, and duplicate an instance's
database (and optionally filestore) from a template. Data operations honor
Odoo's copied-vs-moved semantics (UUID regeneration) and optional neutralization
of the target.

## Requirements

### Requirement: Backup

The tool SHALL back up an instance's database (as a compressed custom-format
dump) and/or its filestore (as a gzipped tar) into a timestamped file in the
chosen backup directory.

#### Scenario: Database backup produces a timestamped custom dump

- **WHEN** the operator selects a backup that includes the database
- **THEN** the plan runs `pg_dump -Fc` for the source database into `<backup_dir>/<instance>_<timestamp>.dump`

#### Scenario: Filestore backup archives the resolved filestore path

- **WHEN** the operator selects a backup that includes the filestore
- **THEN** the plan tars the resolved filestore directory for the source database into `<backup_dir>/<instance>_<timestamp>.filestore.tar.gz`

### Requirement: Restore

Restoring SHALL create the target database from a selected dump and/or restore a
filestore archive, refusing to clobber an existing target database, and require
phrase confirmation before applying.

#### Scenario: Existing target database blocks restore

- **WHEN** the restore includes the database and the target database already exists
- **THEN** the operation reports the conflict and stops without executing

#### Scenario: Existing target filestore requires explicit overwrite

- **WHEN** the restore includes the filestore and the target filestore exists
- **THEN** the operator must confirm overwrite; on confirmation the previous filestore contents are cleared before extracting, otherwise the restore is cancelled

#### Scenario: Restore is phrase-confirmed

- **WHEN** the restore plan is assembled
- **THEN** it executes only after the operator types the exact `RESTORE <instance>` phrase

### Requirement: Duplication

The tool SHALL duplicate a source database into a new target using PostgreSQL
template copy, refusing to overwrite an existing target instance, service,
database, or filestore, and require phrase confirmation.

#### Scenario: Pre-existing target resources block duplication

- **WHEN** the target home, systemd service, database, or (when duplicating the filestore) target filestore already exists
- **THEN** the operation reports the specific conflict and stops without executing

#### Scenario: Duplication copies via template and is phrase-confirmed

- **WHEN** the duplication plan is assembled
- **THEN** it creates the target database with `createdb -T <source>` (optionally copying the filestore) and runs only after the operator types the exact `DUPLICAR <instance>` phrase

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
