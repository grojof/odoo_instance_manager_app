## MODIFIED Requirements

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

### Requirement: Duplication

The tool SHALL duplicate a source database into a new target using PostgreSQL template copy, refusing to
overwrite an existing target instance, service, database, or filestore, and require phrase confirmation. The
duplicated filestore SHALL be placed under the **target** instance's data directory.

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

## ADDED Requirements

### Requirement: Database name path safety

An operator-entered database name SHALL be validated as a safe single path component before it is interpolated
into a filestore path that is created, archived, or deleted.

#### Scenario: Traversal in a database name is refused

- **WHEN** a database name used for backup, restore, or filestore deletion contains a path separator or a
  `.`/`..` traversal component
- **THEN** the operation is refused with a descriptive error and no filestore command is built or executed
