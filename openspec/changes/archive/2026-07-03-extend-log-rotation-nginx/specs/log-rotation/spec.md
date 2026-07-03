## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Query log rotation state

The tool SHALL report an instance's log-rotation state read-only: the Odoo log path, whether a system
logrotate policy exists (and its content), a dry-run preview, current log file sizes, the state of Odoo's
built-in `logrotate` flag, and who rotates the instance's Nginx logs.

#### Scenario: Query reports the current state without changes

- **WHEN** the operator queries log rotation for an instance
- **THEN** the tool shows the Odoo log path, the system logrotate policy (or that none exists), a
  `logrotate -d` dry-run preview when a policy exists, the current log file sizes, and Odoo's built-in
  `logrotate` value, without producing or applying any mutating command

#### Scenario: Nginx rotation coverage is reported

- **WHEN** the query runs
- **THEN** it reports whether the instance's Nginx logs are rotated by the distribution's own `nginx`
  logrotate, by this tool's policy, or by neither
