# log-rotation Specification

## Purpose
TBD - created by archiving change add-log-rotation. Update Purpose after archive.
## Requirements
### Requirement: Configure system log rotation

The tool SHALL configure a system `logrotate` policy for an instance's Odoo log at
`/etc/logrotate.d/odoo-<instance>`, with operator-chosen frequency, retention count, optional compression, and
optional size threshold, using `copytruncate` so the running service is not restarted.

#### Scenario: Rotation policy is written and validated

- **WHEN** the operator configures log rotation for an instance
- **THEN** the plan ensures `logrotate` is installed, writes `/etc/logrotate.d/odoo-<instance>` for
  `/var/log/odoo/<instance>.log` with the chosen frequency/retention/compression (and `copytruncate` plus an
  `su <user> <user>` directive), and validates it with `logrotate -d`

#### Scenario: Size threshold is honored when requested

- **WHEN** the operator opts to also rotate on a size threshold
- **THEN** the generated policy includes a `maxsize` directive with the chosen value

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

### Requirement: Rotate Nginx logs when not covered by the system

When the distribution's own Nginx logrotate does not already cover the instance's Nginx logs, the tool SHALL
offer to rotate them using the Nginx-idiomatic method — `create` plus a `postrotate` SIGUSR1 reopen — rather
than `copytruncate`.

#### Scenario: Uncovered Nginx logs are offered and added with reopen

- **WHEN** `/etc/logrotate.d/nginx` does not cover `/var/log/nginx/*.log` and the operator opts to include the
  instance's Nginx logs
- **THEN** the policy adds a stanza for `<instance>.access.log` and `<instance>.error.log` with
  `create 0640 www-data adm`, `sharedscripts`, and a `postrotate` that reopens Nginx via
  `kill -USR1 $(cat /run/nginx.pid)` — not `copytruncate`

#### Scenario: Covered Nginx logs are not duplicated

- **WHEN** the distribution's Nginx logrotate already covers `/var/log/nginx/*.log`
- **THEN** the tool does not add a second Nginx policy and reports that the system already rotates them

### Requirement: Clean up the obsolete Odoo logrotate key

The tool SHALL NOT write Odoo's built-in `logrotate` option in the generated `odoo.conf` (it was removed in
Odoo 13), and SHALL offer to delete a stale `logrotate` key from an existing conf when one is present.

#### Scenario: Stale logrotate key is removed on request

- **WHEN** the instance's `odoo.conf` contains a `logrotate` key and the operator accepts removing it
- **THEN** the plan deletes the `logrotate` line from the config

#### Scenario: No stale key means nothing to clean

- **WHEN** the `odoo.conf` has no `logrotate` key
- **THEN** no config edit is offered or performed

