# instance-removal Specification

## Purpose

Remove an instance and its residues. Two levels are supported: a scoped delete
of an instance's service, config, home, Nginx vhosts, and SSL (optionally its
database and filestore), and a total superuser purge that additionally removes
the Linux user, logs, all databases matching the instance, and PostgreSQL roles.
Both are gated by an exact confirmation phrase.

## Requirements

### Requirement: Scoped instance delete

The tool SHALL remove an instance's systemd service, its scheduled-backup timer, Odoo config, home, Nginx
vhosts (available and enabled), and SSL directory, and MAY additionally drop the database and remove one
database's filestore when the operator opts in. Removing the home SHALL NOT remove filestores the operator did
not ask to remove: when the instance's data dir lies inside its home (no `data_dir` outside it in `odoo.conf`),
the plan SHALL first move the data dir to a private `/var/backups/<instance>/kept-data-dir-<timestamp>`. When a
database drop is requested for a database that does not exist, the tool SHALL warn and skip the drop rather
than fail the operation.

#### Scenario: System residues are removed and Nginx reloaded

- **WHEN** the operator deletes an instance
- **THEN** the plan stops and disables the service, removes the unit and reloads systemd, removes the backup
  timer, the config dir, home, both Nginx vhosts, and the SSL dir, then validates and reloads Nginx

#### Scenario: The data dir survives the removal of the home

- **WHEN** the instance's data dir lies inside its home
- **THEN** the plan moves it to `/var/backups/<instance>/kept-data-dir-<timestamp>` before removing the home,
  so every filestore the operator did not ask to remove is kept

#### Scenario: Optional database and filestore removal

- **WHEN** the operator opts to drop the database and/or remove a filestore
- **THEN** the plan adds a `dropdb --if-exists` for the named database and/or an `rm -rf` of that database's
  resolved filestore path (a name Odoo accepts as a database name), before the data dir is moved

#### Scenario: Non-existent database is skipped with a warning

- **WHEN** the operator requests dropping a database that is not found with the given credentials (absent or
  unreachable)
- **THEN** the tool warns that the database was not found and omits the drop, continuing with the rest of the
  removal instead of crashing

#### Scenario: Delete is phrase-confirmed

- **WHEN** the delete plan is assembled
- **THEN** it executes only after the operator types the exact `DELETE <instance>` phrase

### Requirement: Total superuser purge

The tool SHALL provide a total purge that, in addition to the scoped removal, deletes the instance's Linux
user, its Odoo/Nginx logs, its fail2ban jail, its backup timer, the filestore root, the instance's databases,
and the instance's PostgreSQL roles. Database discovery SHALL select a database only when the instance's DB
role (which the tool prompts for and validates) owns it or its name equals the instance name. Databases whose
name merely starts with the instance name SHALL be reported to the operator and SHALL NOT be selected; the
operator may add any of them as an extra.

#### Scenario: Databases are discovered from filestore, by prefix, and by owner

- **WHEN** the purge collects databases to remove
- **THEN** it gathers filestore-derived database names and, when admin DB access is available, the databases
  owned by the instance's DB role or named exactly like the instance, plus any operator-supplied extras that are
  valid database names

#### Scenario: Look-alike databases are reported, not selected

- **WHEN** a database's name starts with the instance name (with `_` and `%` matched literally) but the
  instance's role does not own it
- **THEN** the tool lists it as not selected, and it is dropped only if the operator adds it as an extra

#### Scenario: A role shared with another instance selects nothing and is kept

- **WHEN** another instance's `odoo.conf` connects as the same DB role
- **THEN** the tool warns, selects no database by owner (only the one named like the instance), and does not
  drop that role

#### Scenario: Admin DB access enables role and database deletion

- **WHEN** admin PostgreSQL access is resolved (local `sudo -u postgres` or validated remote admin credentials)
- **THEN** the plan drops each candidate database (locally with `dropdb --force`; remotely after terminating
  its sessions), and drops the role the operator named and the instance-named role; without admin access it
  warns and performs local cleanup only

#### Scenario: The fail2ban jail goes with the log

- **WHEN** the purge removes the instance's Odoo log
- **THEN** it also removes the instance's fail2ban jail and reloads fail2ban when it is running, since fail2ban
  refuses to start with a jail whose log file is missing

#### Scenario: Purge shows a summary and is phrase-confirmed

- **WHEN** the purge plan is assembled
- **THEN** it presents a summary of detected resources and executes only after the operator types the exact
  `DELETE-ALL <instance>` phrase
