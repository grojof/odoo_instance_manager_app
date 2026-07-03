# instance-configuration Specification

## Purpose

Inspect and adjust an already-installed instance without destroying data:
discover instances under `/opt/odoo`, show a technical status summary, update
the instance configuration (with a pre-update backup), repair Nginx per-instance
log files, and install Python packages into the instance virtualenv.

## Requirements

### Requirement: Instance discovery and selection

The tool SHALL discover instances as directories under `/opt/odoo` and let the
operator select a detected instance or type a known name, and SHALL optionally
query PostgreSQL to list available databases for validation.

#### Scenario: Detected instances are listed for selection

- **WHEN** the operator enters instance management
- **THEN** directories under `/opt/odoo` are listed for selection, with options to type a name manually or cancel

#### Scenario: Optional database listing for validation

- **WHEN** the operator opts to connect to PostgreSQL during management
- **THEN** the tool lists non-template databases and lets the operator pick one as the validation target, or reports the connection error without blocking management

### Requirement: Instance status inspection

The tool SHALL render the instance's expected paths and a detected-state table
covering the Linux user, home, config file, systemd service (existence and
active state), DB role, data dir, TLS certificate mode, and optional database
existence.

#### Scenario: Status reflects presence of each resource

- **WHEN** the status view is shown
- **THEN** each checked resource is marked present or missing, the TLS certificate mode is classified (self-signed / custom-CA / external / Let's Encrypt / not configured), and useful values from the Odoo config are displayed when the config file exists

### Requirement: Configuration update with pre-update backup

Updating an existing instance's configuration SHALL first back up the current
config, systemd unit, and Nginx vhosts into a timestamped directory, then
regenerate the config and unit, and optionally regenerate the Nginx vhost.

#### Scenario: Existing files are backed up before regeneration

- **WHEN** the operator updates an instance configuration
- **THEN** the plan copies the current config, unit, and Nginx vhosts into `/var/backups/<instance>/config_preupdate/<timestamp>/` before writing new versions

#### Scenario: Autostart state is preserved across update

- **WHEN** the configuration is regenerated
- **THEN** the service autostart choice mirrors whether the service is currently enabled at boot

### Requirement: Nginx log repair

The tool SHALL recreate the per-instance Nginx access and error log files with
correct ownership and permissions, then reopen Nginx logs.

#### Scenario: Instance logs are recreated and reopened

- **WHEN** the operator repairs Nginx logs for an instance
- **THEN** the plan ensures `/var/log/nginx`, recreates `<instance>.access.log` and `<instance>.error.log` owned `www-data:adm` mode `640`, validates Nginx, and reopens logs (falling back to reload)

### Requirement: Virtualenv package installation

The tool SHALL install Python packages into the instance virtualenv either from
a selected requirements file or from an operator-provided package list, running
pip as the instance user.

#### Scenario: Install from a requirements file

- **WHEN** the operator selects a requirements file
- **THEN** the plan validates the venv and the file, then installs the requirements into the venv as the instance user and prints the resulting package list

#### Scenario: Install from a manual package list

- **WHEN** the operator provides packages inline and/or one per line
- **THEN** the plan installs the parsed, non-empty package set into the venv as the instance user; if no valid package is found the operation is cancelled
