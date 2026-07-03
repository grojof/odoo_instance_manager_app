# instance-provisioning Specification

## Purpose

Install and provision Odoo Community instances and their PostgreSQL backing on
an Ubuntu server: an Odoo-only instance, a PostgreSQL-only setup, or both
together. Provisioning is idempotent where possible (create-if-missing) and
always renders a plan before applying.
## Requirements
### Requirement: Install modes

The tool SHALL offer three provisioning modes: Odoo only, PostgreSQL only, and
Odoo + PostgreSQL together.

#### Scenario: Install Odoo only

- **WHEN** the operator chooses to install an Odoo instance without a database server
- **THEN** the plan ensures the instance's DB role/login, performs the Odoo base setup, and optionally configures Nginx, without installing PostgreSQL

#### Scenario: Install PostgreSQL only

- **WHEN** the operator chooses to install PostgreSQL without Odoo
- **THEN** the plan installs and enables PostgreSQL, ensures the instance role, validates the role login, and optionally opens remote access

#### Scenario: Install Odoo and PostgreSQL together

- **WHEN** the operator chooses the combined install
- **THEN** the plan performs the DB setup (with remote access) followed by the Odoo base setup, and optionally configures Nginx

### Requirement: Odoo base setup

The Odoo base setup SHALL install OS dependencies, create the instance system user and directory layout, clone
the Odoo repository at the requested branch, build a virtualenv with requirements, write the instance config
and systemd unit, and register the service.

#### Scenario: Instance directories and user are created

- **WHEN** the base setup runs for a new instance
- **THEN** it creates the system user (if missing), the `/opt/odoo/<instance>` home with `odoo`, `addons-oca`,
  `addons-custom` subdirs, the `/etc/odoo/<instance>` config dir, and `/var/log/odoo`, with correct ownership
  and a `750` config dir

#### Scenario: Odoo repo and venv are prepared

- **WHEN** the base setup runs
- **THEN** it clones `odoo` at the requested branch only if absent, and creates/updates the venv installing
  `requirements.txt`

#### Scenario: Config and unit files are written with restrictive permissions

- **WHEN** the base setup writes the instance config and systemd unit
- **THEN** `<instance>.conf` is written mode `640` owned `root:<instance>`, and the systemd unit is written
  mode `644`, followed by a systemd daemon-reload

#### Scenario: Service autostart is operator-controlled

- **WHEN** the operator opts into service autostart
- **THEN** the plan enables and starts the service; otherwise it explicitly disables autostart and then starts
  the service (running now but not enabled at boot)

### Requirement: Database role provisioning

The tool SHALL ensure the instance's PostgreSQL role exists with LOGIN and
CREATEDB, creating it only if missing and never overwriting the password of an
existing role, and SHALL validate the role can log in.

#### Scenario: Missing local role is created

- **WHEN** the DB host is local and the role does not exist
- **THEN** the plan creates the role with LOGIN CREATEDB using the configured password

#### Scenario: Existing role is preserved

- **WHEN** the role already exists
- **THEN** the plan re-asserts LOGIN CREATEDB but does not change the existing password, emitting a notice that the role is reused

#### Scenario: Remote DB host skips role creation

- **WHEN** the DB host is remote
- **THEN** the plan skips role creation (no admin credentials assumed) and only validates the configured user's login

### Requirement: Remote database access

When installing PostgreSQL with remote access enabled, the plan SHALL set
`listen_addresses='*'` and append a host-scoped `pg_hba` rule for the app
server IP using `scram-sha-256`, then restart PostgreSQL.

#### Scenario: Remote access is opened for the app server

- **WHEN** remote access is enabled during a DB install
- **THEN** the plan edits the resolved `postgresql.conf` for `listen_addresses='*'`, ensures a `pg_hba` line for `<db_user> <app_server_ip>/32 scram-sha-256` (idempotently), and restarts PostgreSQL

### Requirement: Safe configuration defaults

When required credential values are left blank, the tool SHALL default the DB
user, DB password, and Odoo admin password to the instance name before building
any plan.

#### Scenario: Blank credentials default to the instance name

- **WHEN** the operator leaves DB user, DB password, or admin password empty
- **THEN** each blank value is set to the instance name during normalization

### Requirement: Optional log rotation at install

When provisioning an instance that installs Odoo, the tool SHALL offer to set up system log rotation for the
instance's Odoo log, defaulting to enabled.

#### Scenario: Log rotation is set up by default on install

- **WHEN** the operator provisions an Odoo instance and accepts the (default-yes) log-rotation prompt
- **THEN** the install plan includes a system logrotate policy for `/var/log/odoo/<instance>.log`

#### Scenario: Log rotation can be declined at install

- **WHEN** the operator declines the log-rotation prompt
- **THEN** the install plan adds no logrotate commands

