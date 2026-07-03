## MODIFIED Requirements

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
overwrite an existing target instance, service, database, or filestore, and require phrase confirmation. The
duplicated filestore SHALL be placed under the **target** instance's data directory. Duplication copies the
database and (optionally) the filestore only; it does **not** provision the target instance's service, config,
or system user.

#### Scenario: Pre-existing target resources block duplication

- **WHEN** the target home, systemd service, database, or (when duplicating the filestore) target filestore
  already exists
- **THEN** the operation reports the specific conflict and stops without executing

#### Scenario: Duplication copies via template and is phrase-confirmed

- **WHEN** the duplication plan is assembled
- **THEN** it creates the target database with `createdb -T <source>` (optionally copying the filestore) and
  runs only after the operator types the exact `DUPLICAR <instance>` phrase

#### Scenario: Duplicated filestore lands under the target instance

- **WHEN** the filestore is duplicated
- **THEN** the copy is written under the target instance's data directory (resolved from the target instance),
  not the source instance's, so the duplicated instance has its attachments

#### Scenario: Duplication does not provision the target instance

- **WHEN** duplication completes
- **THEN** only the database and (optionally) filestore exist for the target; provisioning its service, config,
  and user remains a separate install step
