# scheduled-backups Specification

## Purpose
Back up an instance's database, and optionally its filestore, on a systemd timer: private files, a run that fails whenever the dump, its check or the archive fails, and retention per database — with the timer's status and removal at hand.

## Requirements

### Requirement: Configure a scheduled backup

The tool SHALL install a systemd service and timer that back up an instance's database (via local
`sudo -u postgres pg_dump`) and, optionally, its filestore, applying retention, on an operator-chosen schedule.
The script SHALL take every value shell-quoted, SHALL write private files (`umask 077`, directory `700`, unit
`UMask=0077`), SHALL leave no partial file behind, and SHALL exit non-zero when the dump fails, when the dump has
no readable table of contents (`pg_restore --list`), when the filestore directory is missing, or when the
archive fails — so the unit shows failed instead of reporting a backup that is not there.

#### Scenario: A timer and backup script are installed

- **WHEN** the operator configures a scheduled backup with a database, destination, schedule, and retention
- **THEN** the plan writes `/usr/local/sbin/odoo-backup-<instance>.sh`, an `odoo-backup-<instance>.service`, and
  an `odoo-backup-<instance>.timer` with the chosen `OnCalendar`, reloads systemd, and enables and starts the
  timer

#### Scenario: A failed dump fails the run

- **WHEN** `pg_dump` fails or produces a dump `pg_restore --list` cannot read
- **THEN** the script exits non-zero, removes the partial file, and writes no `.dump`

#### Scenario: Filestore is optional

- **WHEN** the operator declines including the filestore
- **THEN** the backup script dumps only the database (no filestore archive)

#### Scenario: Retention prunes old backups

- **WHEN** the scheduled backup runs
- **THEN** it keeps the chosen number of newest dumps (and filestore archives) named
  `<instance>--<db>--<timestamp>` and removes the older ones, never touching other instances' or other
  databases' backups

### Requirement: Inspect and remove a scheduled backup

The tool SHALL show the timer status and next run, and SHALL remove the schedule (disable the timer, delete the
units and script).

#### Scenario: Status shows the timer and next run

- **WHEN** the operator views the scheduled-backup status
- **THEN** the tool shows the timer's systemd status and its next scheduled run (read-only)

#### Scenario: Removal disables the timer and deletes the files

- **WHEN** the operator removes the schedule
- **THEN** the plan disables/stops the timer and deletes the timer, service, and script, then reloads systemd
