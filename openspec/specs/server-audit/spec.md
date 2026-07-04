# server-audit Specification

## Purpose

Produce a read-only audit report of an Ubuntu server hosting Odoo, intended to
hand off to an external server. The report discovers Odoo instances from systemd
units, configs, Nginx vhosts, and filestores, and summarizes system facts, per
-instance technical detail, TLS posture, and detected Odoo release versions —
without changing anything.
## Requirements
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

### Requirement: TLS posture reporting

The report SHALL classify each instance's TLS material (self-signed, Let's
Encrypt, custom, incomplete, or none) and report certificate metadata and
expiry status against a threshold.

#### Scenario: Certificate expiry is classified against a threshold

- **WHEN** an instance vhost references a certificate
- **THEN** the report classifies the certificate type and marks it OK, WARN (expiring within the threshold), MISSING, or ERROR based on `openssl` checks

### Requirement: Odoo version detection

The report SHALL detect each instance's Odoo release version from the checked-out
source `release.py` when available.

#### Scenario: Release version is read from source

- **WHEN** an instance's Odoo home is known
- **THEN** the report reads `version_info` from `<home>/odoo/odoo/release.py` and reports the major.minor version, or blank when unavailable

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

### Requirement: Production posture reporting

The report SHALL include, per discovered instance, a production-posture summary derived read-only from
each instance config and the host: database-manager exposure (`list_db`), the presence of a guessable
default master or DB password, worker sizing versus detected CPU, `db_sslmode` for remote database
hosts, and `dbfilter` presence; and it SHALL report the host `wkhtmltopdf` version once. The summary
SHALL NOT modify anything.

#### Scenario: Posture is reported per instance

- **WHEN** the report is generated
- **THEN** each discovered instance shows its `list_db`, credential-default, worker-sizing,
  remote-`db_sslmode`, and `dbfilter` posture with an OK/WARN/INFO classification

#### Scenario: Host wkhtmltopdf version is reported

- **WHEN** the report is generated
- **THEN** the host `wkhtmltopdf` version is reported (or a not-detected marker), and a missing or
  un-patched build is flagged as WARN

#### Scenario: Posture reporting performs no mutation

- **WHEN** the posture summary is produced
- **THEN** only read-only inspection of configs and host state occurs and no install, configuration,
  or deletion command is produced or applied

