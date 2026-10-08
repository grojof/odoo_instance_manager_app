# disk-usage Specification

## Purpose
Show what an instance occupies on disk (home, data dir, logs, backups) and the free space where its data lives, read-only, and prune old backups per database and kind without touching another instance's or another database's files.

## Requirements

### Requirement: Disk usage report

The tool SHALL report an instance's disk footprint read-only: the size of its home, data directory
(filestore), logs, and backup directory, plus the free space of the filesystem holding the data directory.

#### Scenario: Usage report shows sizes without changes

- **WHEN** the operator views disk usage for an instance
- **THEN** the tool shows the sizes of the home, data dir, Odoo logs, and backup directory, the free space of
  the data-dir filesystem, and a listing of present backup files — running only inspection commands

### Requirement: Backup retention cleanup

The tool SHALL remove an instance's oldest backup artifacts while keeping the operator-chosen number of most
recent ones **per database** and kind (DB dumps and filestore archives), through the standard
preview/confirm/apply flow. Backups SHALL be matched by their exact name pattern
(`<instance>--<db>--<timestamp>` plus the kind's suffix), so another instance's or another database's backups
are never removed. Backups named before the database was part of the name (`<instance>_<timestamp>`) SHALL be
pruned as one more group, matched exactly.

#### Scenario: Retention keeps the N newest of each kind

- **WHEN** the operator runs retention cleanup keeping N backups
- **THEN** for each database the instance has backups of, the plan keeps the N newest dumps and the N newest
  filestore archives and removes the older ones, previewed before applying

#### Scenario: Look-alike backups are never pruned

- **WHEN** the backup directory also holds backups of an instance whose name starts with this instance's name
  (`shop_eu` next to `shop`) or of another database of this instance
- **THEN** none of them is removed by this instance's or this database's retention

#### Scenario: Missing backup directory is a no-op

- **WHEN** the backup directory does not exist
- **THEN** the tool reports it and performs no cleanup
