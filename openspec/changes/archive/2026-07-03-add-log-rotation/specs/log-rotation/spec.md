## ADDED Requirements

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

### Requirement: Avoid double rotation with Odoo's built-in logrotate

When the instance's `odoo.conf` still enables Odoo's own `logrotate`, the tool SHALL warn about double
rotation and offer to set `logrotate = False` in the config.

#### Scenario: Built-in logrotate is disabled on request

- **WHEN** the config has `logrotate = True` and the operator accepts disabling it
- **THEN** the plan sets `logrotate = False` in the `odoo.conf` and the tool notes that an Odoo restart applies
  the change

#### Scenario: Built-in logrotate is left untouched when declined

- **WHEN** the operator declines disabling the built-in logrotate
- **THEN** the config is not modified and only the system logrotate policy is written

### Requirement: Query log rotation state

The tool SHALL report an instance's log-rotation state read-only: the Odoo log path, whether a system
logrotate policy exists (and its content), a dry-run preview, current log file sizes, and the state of Odoo's
built-in `logrotate` flag.

#### Scenario: Query reports the current state without changes

- **WHEN** the operator queries log rotation for an instance
- **THEN** the tool shows the Odoo log path, the system logrotate policy (or that none exists), a
  `logrotate -d` dry-run preview when a policy exists, the current log file sizes, and Odoo's built-in
  `logrotate` value, without producing or applying any mutating command

#### Scenario: Nginx rotation ownership is reported

- **WHEN** the query runs
- **THEN** it notes that per-instance Nginx logs are rotated by the distribution's own `nginx` logrotate, which
  this capability does not manage
