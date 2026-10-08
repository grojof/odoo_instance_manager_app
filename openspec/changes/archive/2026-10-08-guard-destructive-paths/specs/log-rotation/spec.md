## MODIFIED Requirements

### Requirement: Configure system log rotation

The tool SHALL configure a system `logrotate` policy for an instance's Odoo log at
`/etc/logrotate.d/odoo-<instance>`, with operator-chosen frequency, retention count, optional compression, and
optional size threshold, using `copytruncate` so the running service is not restarted.

#### Scenario: Rotation policy is written and validated

- **WHEN** the operator configures log rotation for an instance
- **THEN** the plan ensures `logrotate` is installed, writes `/etc/logrotate.d/odoo-<instance>` for
  `/var/log/odoo/<instance>.log` with the chosen frequency/retention/compression and `copytruncate`, with no
  `su` directive (`/var/log/odoo` is root's, so root rotates), and validates it with `logrotate -d`

#### Scenario: Size threshold is honored when requested

- **WHEN** the operator opts to also rotate on a size threshold
- **THEN** the generated policy includes a `maxsize` directive with the chosen value
