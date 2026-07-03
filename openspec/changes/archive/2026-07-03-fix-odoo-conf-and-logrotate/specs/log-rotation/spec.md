## REMOVED Requirements

### Requirement: Avoid double rotation with Odoo's built-in logrotate

## ADDED Requirements

### Requirement: Clean up the obsolete Odoo logrotate key

The tool SHALL NOT write Odoo's built-in `logrotate` option in the generated `odoo.conf` (it was removed in
Odoo 13), and SHALL offer to delete a stale `logrotate` key from an existing conf when one is present.

#### Scenario: Stale logrotate key is removed on request

- **WHEN** the instance's `odoo.conf` contains a `logrotate` key and the operator accepts removing it
- **THEN** the plan deletes the `logrotate` line from the config

#### Scenario: No stale key means nothing to clean

- **WHEN** the `odoo.conf` has no `logrotate` key
- **THEN** no config edit is offered or performed

## MODIFIED Requirements

### Requirement: Query log rotation state

The tool SHALL report an instance's log-rotation state read-only: whether rotation of the Odoo log is active,
the Odoo log path, whether a system logrotate policy exists (and its content), a dry-run preview, current log
file sizes, and who rotates the instance's Nginx logs.

#### Scenario: Odoo log rotation status is reported as active or inactive

- **WHEN** the operator queries log rotation for an instance
- **THEN** the tool clearly reports whether rotation of the Odoo log is **active** (a system logrotate policy
  exists covering `/var/log/odoo/<instance>.log`) or **inactive**

#### Scenario: Query reports the current state without changes

- **WHEN** the operator queries log rotation for an instance
- **THEN** the tool shows the Odoo log path, the system logrotate policy (or that none exists), a
  `logrotate -d` dry-run preview when a policy exists, and the current log file sizes, without producing or
  applying any mutating command

#### Scenario: Nginx rotation coverage is reported

- **WHEN** the query runs
- **THEN** it reports whether the instance's Nginx logs are rotated by the distribution's own `nginx`
  logrotate, by this tool's policy, or by neither
