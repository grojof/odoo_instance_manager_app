## MODIFIED Requirements

### Requirement: Backup retention cleanup

The tool SHALL remove an instance's oldest backup artifacts while keeping the operator-chosen number of most
recent ones **per database** and kind (DB dumps and filestore archives), through the standard
preview/confirm/apply flow. Backups SHALL be matched by their exact name pattern
(`<instance>--<db>--<timestamp>` plus the kind's suffix), so another instance's or another database's backups
are never removed. Backups named before the database was part of the name (`<instance>_<timestamp>`) SHALL be
pruned as one more group, matched exactly. The newest backups SHALL be the latest timestamps in their names, not
the latest modification times (a copied or restored file gets a new one), and a database name read from a file
name SHALL be used only when it is a valid database name.

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
