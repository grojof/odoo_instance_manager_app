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

The tool SHALL expose the instance's status as separate, on-demand views reachable from the management
menu — expected locations/names, detected resource state, and useful configuration values — rather
than rendering the full status on every menu display. Each view SHALL be individually selectable so
the operator sees only the requested section, and the detected-state view SHALL cover the Linux user,
home, config file, systemd service (existence and active state), DB role, data dir, TLS certificate
mode, and optional database existence.

#### Scenario: Status is split into selectable views

- **WHEN** the operator opens the management menu for an instance
- **THEN** locations/names, detected resource state, and useful config values are each reachable as a
  separate menu action instead of being printed together

#### Scenario: The management menu does not auto-render the full status

- **WHEN** the management menu is (re)displayed after an action
- **THEN** the full status tables are not re-printed automatically; only the menu (optionally with a
  compact one-line summary) is shown

#### Scenario: Detected-state view marks each resource

- **WHEN** the operator opens the detected-state view
- **THEN** each checked resource (Linux user, home, config, service existence/active, DB role, data
  dir, TLS mode, and optional database) is marked present or missing, and the TLS certificate mode is
  classified (self-signed / custom-CA / external / Let's Encrypt / incomplete / not configured)

### Requirement: Configuration update with pre-update backup

Updating an existing instance's configuration SHALL first back up the current config, systemd unit, and Nginx
vhosts into a single timestamped directory, then **replay the full Odoo base setup** to regenerate the config
and unit, and optionally regenerate the Nginx vhost.

#### Scenario: Existing files are backed up before regeneration

- **WHEN** the operator updates an instance configuration
- **THEN** the plan copies the current config, unit, and Nginx vhosts into a single
  `/var/backups/<instance>/config_preupdate/<timestamp>/` directory before writing new versions

#### Scenario: Update replays the full base setup

- **WHEN** the configuration update is applied
- **THEN** it runs the same base-setup plan as provisioning (package install, user/dir creation, repo clone if
  absent, venv creation and `pip install -r requirements.txt`), not only a config rewrite

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

### Requirement: Security and production posture audit

The management status SHALL provide an on-demand security-and-production posture view that inspects the
instance config and host read-only and reports, each with an OK/WARN/INFO classification and a short
rationale: whether the database manager is exposed (`list_db = True`); whether the master password
(`admin_passwd`) or the DB password is still the guessable instance-name default; whether
`wkhtmltopdf` is installed and its version; whether the worker count is sized for the detected CPU/RAM;
whether `db_sslmode` is set when the DB host is remote; and whether a `dbfilter` is configured.

#### Scenario: Posture view flags an exposed database manager

- **WHEN** the instance config has `list_db = True`
- **THEN** the posture view marks the database-manager exposure as WARN with a rationale recommending
  `list_db = False` (plus `dbfilter`) for production

#### Scenario: Posture view flags guessable default credentials

- **WHEN** the master password or DB password equals the instance name in plaintext
- **THEN** the posture view marks it WARN as a guessable default

#### Scenario: Hashed master password is treated as acceptable

- **WHEN** the master password value in the config is stored hashed (not plaintext)
- **THEN** the posture view does not flag it as a guessable default

#### Scenario: Posture view reports wkhtmltopdf presence and version

- **WHEN** the posture view runs
- **THEN** it reports whether `wkhtmltopdf` is installed and its version, marking a missing or
  un-patched/too-old build as WARN

#### Scenario: Posture view flags an unencrypted remote DB connection

- **WHEN** the DB host is remote and `db_sslmode` is unset or permits cleartext fallback
  (`disable`/`allow`/`prefer`)
- **THEN** the posture view marks the DB connection as WARN and recommends `require` or stricter

