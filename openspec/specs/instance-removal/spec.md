# instance-removal Specification

## Purpose

Remove an instance and its residues. Two levels are supported: a scoped delete
of an instance's service, config, home, Nginx vhosts, and SSL (optionally its
database and filestore), and a total superuser purge that additionally removes
the Linux user, logs, all databases matching the instance, and PostgreSQL roles.
Both are gated by an exact confirmation phrase.
## Requirements
### Requirement: Scoped instance delete

The tool SHALL remove an instance's systemd service, Odoo config, home, Nginx vhosts (available and enabled),
and SSL directory, and MAY additionally drop the database and remove the filestore when the operator opts in.
When a database drop is requested for a database that does not exist, the tool SHALL warn and skip the drop
rather than fail the operation.

#### Scenario: System residues are removed and Nginx reloaded

- **WHEN** the operator deletes an instance
- **THEN** the plan stops and disables the service, removes the unit and reloads systemd, removes the config
  dir, home, both Nginx vhosts, and the SSL dir, then validates and reloads Nginx

#### Scenario: Optional database and filestore removal

- **WHEN** the operator opts to drop the database and/or remove the filestore
- **THEN** the plan adds a `dropdb --if-exists` for the named database and/or an `rm -rf` of the resolved
  filestore path

#### Scenario: Non-existent database is skipped with a warning

- **WHEN** the operator requests dropping a database that is not found with the given credentials (absent or
  unreachable)
- **THEN** the tool warns that the database was not found and omits the drop, continuing with the rest of the
  removal instead of crashing

#### Scenario: Delete is phrase-confirmed

- **WHEN** the delete plan is assembled
- **THEN** it executes only after the operator types the exact `ELIMINAR <instance>` phrase

### Requirement: Total superuser purge

The tool SHALL provide a total purge that, in addition to the scoped removal, deletes the instance's Linux
user, its Odoo/Nginx logs, the filestore root, all databases discovered for the instance, and the instance's
PostgreSQL roles. Database discovery SHALL find the instance's databases by **owner** (the instance's DB user,
which the tool prompts for) as well as by name prefix, so databases associated with the instance are cleaned
even when their name does not start with the instance name.

#### Scenario: Databases are discovered from filestore, by prefix, and by owner

- **WHEN** the purge collects databases to remove
- **THEN** it gathers filestore-derived database names and, when admin DB access is available, databases whose
  name matches the `<instance>%` prefix **or** that are owned by the instance's DB role (which the operator is
  prompted for), plus any operator-supplied extras

#### Scenario: Admin DB access enables role and database deletion

- **WHEN** admin PostgreSQL access is resolved (local `sudo -u postgres` or validated remote admin credentials)
- **THEN** the plan terminates active connections and drops each candidate database, and drops the instance/db-user roles; without admin access it warns and performs local cleanup only

#### Scenario: Purge shows a summary and is phrase-confirmed

- **WHEN** the purge plan is assembled
- **THEN** it presents a summary of detected resources and executes only after the operator types the exact `ELIMINAR-TODO <instance>` phrase

