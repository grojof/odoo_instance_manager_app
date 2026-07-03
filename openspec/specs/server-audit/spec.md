# server-audit Specification

## Purpose

Produce a read-only audit report of an Ubuntu server hosting Odoo, intended to
hand off to an external server. The report discovers Odoo instances from systemd
units, configs, Nginx vhosts, and filestores, and summarizes system facts, per
-instance technical detail, TLS posture, and detected Odoo release versions —
without changing anything.

## Requirements

### Requirement: System overview

The report SHALL summarize host facts: hostname, OS pretty name, kernel,
architecture, virtualization, uptime, IPs, and the versions/paths of Python,
the PostgreSQL client, and Nginx.

#### Scenario: Overview reports detected facts or a not-detected marker

- **WHEN** the report is generated
- **THEN** each system fact is shown with its detected value, or a "not detected" marker when the probe fails, and no probe mutates the system

### Requirement: Instance discovery

The report SHALL discover Odoo instances by cross-referencing systemd units
whose unit content references Odoo, valid Odoo config files, Odoo-related Nginx
vhosts, and filestore roots, deriving each instance's home, config, and Python
from the service `ExecStart` when possible.

#### Scenario: Instances are discovered from multiple signals

- **WHEN** discovery runs
- **THEN** it collects services referencing `odoo-bin`/`Description=Odoo`, config files validated as Odoo configs, Nginx vhosts matching the instance, and existing filestore roots — excluding backup-like and `.ssh` paths

#### Scenario: Config validity excludes backups and non-Odoo files

- **WHEN** a candidate `.conf` is evaluated
- **THEN** it is treated as an Odoo config only if it is not backup-like and contains at least two expected Odoo keys

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

The audit SHALL be strictly read-only: it runs discovery and inspection commands
but never builds or applies a mutating plan.

#### Scenario: Report never mutates the server

- **WHEN** the full report runs
- **THEN** only inspection/discovery commands execute and no install, configuration, or deletion command is produced or applied
