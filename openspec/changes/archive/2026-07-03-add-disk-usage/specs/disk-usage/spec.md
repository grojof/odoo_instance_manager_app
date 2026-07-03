## ADDED Requirements

### Requirement: Disk usage report

The tool SHALL report an instance's disk footprint read-only: the size of its home, data directory
(filestore), logs, and backup directory, plus the free space of the filesystem holding the data directory.

#### Scenario: Usage report shows sizes without changes

- **WHEN** the operator views disk usage for an instance
- **THEN** the tool shows the sizes of the home, data dir, Odoo logs, and backup directory, the free space of
  the data-dir filesystem, and a listing of present backup files — running only inspection commands

### Requirement: Backup retention cleanup

The tool SHALL remove an instance's oldest backup artifacts while keeping the operator-chosen number of most
recent ones of each kind (DB dumps and filestore archives), through the standard preview/confirm/apply flow.

#### Scenario: Retention keeps the N newest of each kind

- **WHEN** the operator runs retention cleanup keeping N backups
- **THEN** the plan keeps the N newest `*.dump` and the N newest `*.filestore.tar.gz` for the instance and
  removes the older ones, previewed before applying

#### Scenario: Missing backup directory is a no-op

- **WHEN** the backup directory does not exist
- **THEN** the tool reports it and performs no cleanup
