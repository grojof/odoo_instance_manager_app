## MODIFIED Requirements

### Requirement: Scoped instance delete

The tool SHALL remove an instance's systemd service, its scheduled-backup timer, Odoo config, logrotate policy,
home, Nginx vhosts (available and enabled), and SSL directory, and MAY additionally drop the database and remove
one database's filestore when the operator opts in. Removing the home SHALL NOT remove filestores the operator
did not ask to remove: when the instance's data dir (read from its `odoo.conf`, current or legacy location) lies
inside its home, the plan SHALL first move it to a private `/var/backups/<instance>/kept-data-dir-<timestamp>`.
A database SHALL be dropped only when it exists and belongs to the instance's role (from its `odoo.conf`); the
tool SHALL warn and skip the drop otherwise rather than fail the operation. Nginx SHALL be validated and
reloaded only when it is installed, and its failure SHALL NOT stop the removal.

#### Scenario: System residues are removed and Nginx reloaded

- **WHEN** the operator deletes an instance
- **THEN** the plan stops and disables the service, removes the unit and reloads systemd, removes the backup
  timer, the config dir, the logrotate policy, home, both Nginx vhosts, and the SSL dir, then validates and
  reloads Nginx when it is installed

#### Scenario: The data dir survives the removal of the home

- **WHEN** the instance's data dir lies inside its home
- **THEN** the plan moves it to `/var/backups/<instance>/kept-data-dir-<timestamp>` before removing the home,
  so every filestore the operator did not ask to remove is kept

#### Scenario: Optional database and filestore removal

- **WHEN** the operator opts to drop the database and/or remove a filestore
- **THEN** the plan adds a `dropdb --if-exists` for the named database (a name Odoo accepts, owned by the
  instance's role) before the config is removed, and/or an `rm -rf` of that database's resolved filestore path

#### Scenario: Another role's database is not dropped

- **WHEN** the database to drop belongs to a role other than the instance's
- **THEN** the tool reports it and omits the drop

#### Scenario: Non-existent database is skipped with a warning

- **WHEN** the operator requests dropping a database that is not found with the given credentials (absent or
  unreachable)
- **THEN** the tool warns that the database was not found and omits the drop, continuing with the rest of the
  removal instead of crashing

#### Scenario: A host without nginx still removes the instance

- **WHEN** nginx is not installed, or `nginx -t` fails because of another site
- **THEN** the removal completes and nginx is not reloaded

#### Scenario: Delete is phrase-confirmed

- **WHEN** the delete plan is assembled
- **THEN** it executes only after the operator types the exact `DELETE <instance>` phrase

### Requirement: Total superuser purge

The tool SHALL provide a total purge that, in addition to the scoped removal, deletes the instance's Linux
user, its Odoo/Nginx logs, its logrotate policy, its fail2ban jail, its backup timer, its filestores, the
instance's databases, and the instance's PostgreSQL roles. Database discovery SHALL select a database only when
the instance's DB role (read from its `odoo.conf`, prompted and validated) owns it or its name equals the
instance name. A filestore folder alone SHALL NOT select a database, and databases whose name merely starts with
the instance name SHALL be reported and SHALL NOT be selected; the operator may add any of them as an extra.
The instance role SHALL NOT be `postgres`, the admin user, or a superuser. The databases SHALL be dropped before
their filestores are removed. A data dir that is the instance's own (`/var/lib/odoo/<instance>`, or one inside
the home) SHALL be removed whole; any other data dir may be shared, so only the selected databases' filestores
SHALL be removed from it. The Linux user SHALL be removed only when its home is `/opt/odoo/<instance>`, without
`userdel -r`.

#### Scenario: Databases are selected by owner or exact name

- **WHEN** the purge collects databases to remove
- **THEN** it selects, when admin DB access is available, the databases owned by the instance's DB role or
  named exactly like the instance, plus any operator-supplied extras that are valid database names; filestore
  folders of databases it did not select are listed as not selected

#### Scenario: Look-alike databases are reported, not selected

- **WHEN** a database's name starts with the instance name (with `_` and `%` matched literally) but the
  instance's role does not own it
- **THEN** the tool lists it as not selected, and it is dropped only if the operator adds it as an extra

#### Scenario: An administrator role is refused

- **WHEN** the role given for the instance is `postgres`, the admin user, or a superuser, or cannot be checked
- **THEN** the tool refuses and builds no plan

#### Scenario: A role shared with another instance selects nothing and is kept

- **WHEN** another instance's `odoo.conf` connects as the same DB role, or as the role named after the instance
- **THEN** the tool warns, selects no database by owner (only the one named like the instance), and does not
  drop that role

#### Scenario: A shared data dir keeps other instances' filestores

- **WHEN** the instance's data dir is not its own (for example `/var/lib/odoo` or a custom path)
- **THEN** the plan removes only `filestore/<db>` of the selected databases from it

#### Scenario: The managed data dir is found after a delete

- **WHEN** `/var/lib/odoo/<instance>` exists but the instance's `odoo.conf` is gone
- **THEN** the purge still lists its filestores and removes it

#### Scenario: Admin DB access enables role and database deletion

- **WHEN** admin PostgreSQL access is resolved (local `sudo -u postgres` or validated remote admin credentials)
- **THEN** the plan drops each selected database (locally with `dropdb --force`; remotely after terminating
  its sessions) right after stopping the service, and drops the role the operator named and the instance-named
  role, reporting a role it could not drop; without admin access it warns and performs local cleanup only

#### Scenario: An account the tool did not make is kept

- **WHEN** the instance's Linux user exists but its home is not `/opt/odoo/<instance>`
- **THEN** the purge keeps it and says so

#### Scenario: The fail2ban jail goes with the log

- **WHEN** the purge removes the instance's Odoo log
- **THEN** it also removes the instance's fail2ban jail and reloads fail2ban when it is running, since fail2ban
  refuses to start with a jail whose log file is missing

#### Scenario: Purge shows a summary and is phrase-confirmed

- **WHEN** the purge plan is assembled
- **THEN** it presents a summary of detected resources and executes only after the operator types the exact
  `DELETE-ALL <instance>` phrase
