# scheduled-backups Specification

## Purpose
TBD - created by archiving change add-scheduled-backups. Update Purpose after archive.
## Requirements
### Requirement: Configure a scheduled backup

The tool SHALL install a systemd service and timer that back up an instance's database (via local
`sudo -u postgres pg_dump`) and, optionally, its filestore, applying retention, on an operator-chosen schedule.

#### Scenario: A timer and backup script are installed

- **WHEN** the operator configures a scheduled backup with a database, destination, schedule, and retention
- **THEN** the plan writes `/usr/local/sbin/odoo-backup-<instance>.sh`, an `odoo-backup-<instance>.service`, and
  an `odoo-backup-<instance>.timer` with the chosen `OnCalendar`, reloads systemd, and enables and starts the
  timer

#### Scenario: Filestore is optional

- **WHEN** the operator declines including the filestore
- **THEN** the backup script dumps only the database (no filestore archive)

#### Scenario: Retention prunes old backups

- **WHEN** the scheduled backup runs
- **THEN** it keeps the chosen number of newest dumps (and filestore archives) and removes the older ones

### Requirement: Inspect and remove a scheduled backup

The tool SHALL show the timer status and next run, and SHALL remove the schedule (disable the timer, delete the
units and script).

#### Scenario: Status shows the timer and next run

- **WHEN** the operator views the scheduled-backup status
- **THEN** the tool shows the timer's systemd status and its next scheduled run (read-only)

#### Scenario: Removal disables the timer and deletes the files

- **WHEN** the operator removes the schedule
- **THEN** the plan disables/stops the timer and deletes the timer, service, and script, then reloads systemd

