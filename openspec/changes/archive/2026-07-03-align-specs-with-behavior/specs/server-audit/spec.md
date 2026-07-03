## MODIFIED Requirements

### Requirement: System overview

The report SHALL summarize host facts: hostname, OS pretty name, kernel, architecture, virtualization, uptime,
IPs, and the versions/paths of Python, the PostgreSQL client, and Nginx, and SHALL include the run/boot state
of the PostgreSQL and Nginx services and an `nginx -t` configuration probe.

#### Scenario: Overview reports detected facts or a not-detected marker

- **WHEN** the report is generated
- **THEN** each system fact is shown with its detected value, or a "not detected" marker when the probe fails,
  and no probe mutates the system

#### Scenario: Service and config health are reported

- **WHEN** the overview is generated
- **THEN** it includes whether PostgreSQL and Nginx are active and enabled and the result of a read-only
  `nginx -t` probe

### Requirement: Instance discovery

The report SHALL discover Odoo instances by cross-referencing systemd units whose unit content references Odoo,
valid Odoo config files (including the legacy `/etc/<instance>/odoo.conf` path), Odoo-related Nginx vhosts, and
filestore roots, deriving each instance's home, config, and Python from the service `ExecStart` when possible.

#### Scenario: Instances are discovered from multiple signals

- **WHEN** discovery runs
- **THEN** it collects services referencing `odoo-bin`/`Description=Odoo`, config files validated as Odoo
  configs (default `/etc/odoo/<instance>/<instance>.conf` and legacy `/etc/<instance>/odoo.conf`), Nginx vhosts
  matching the instance, and existing filestore roots — excluding backup-like and `.ssh` paths

#### Scenario: Config validity excludes backups and non-Odoo files

- **WHEN** a candidate `.conf` is evaluated
- **THEN** it is treated as an Odoo config only if it is not backup-like and contains at least two expected Odoo
  keys

### Requirement: Read-only guarantee

The audit SHALL be read-only with respect to server configuration: it runs discovery and inspection commands
and never builds or applies a plan that installs, configures, or deletes anything. It MAY, at the operator's
request, write a single report file and run active (read-only) TLS certificate checks.

#### Scenario: Report never mutates server configuration

- **WHEN** the full report runs
- **THEN** only inspection/discovery commands execute and no install, configuration, or deletion command is
  produced or applied

#### Scenario: Optional report export is operator-initiated

- **WHEN** the operator opts to export the report
- **THEN** the tool writes a single report file to the chosen path (default under `./reports/`), which is the
  only file the audit creates

#### Scenario: Optional active TLS checks are read-only

- **WHEN** the operator opts into active TLS checks with an expiry threshold
- **THEN** the tool runs read-only `openssl` certificate checks and does not modify any certificate or service
