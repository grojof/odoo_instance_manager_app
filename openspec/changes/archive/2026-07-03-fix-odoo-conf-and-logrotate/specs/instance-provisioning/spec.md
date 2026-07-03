## ADDED Requirements

### Requirement: Optional log rotation at install

When provisioning an instance that installs Odoo, the tool SHALL offer to set up system log rotation for the
instance's Odoo log, defaulting to enabled.

#### Scenario: Log rotation is set up by default on install

- **WHEN** the operator provisions an Odoo instance and accepts the (default-yes) log-rotation prompt
- **THEN** the install plan includes a system logrotate policy for `/var/log/odoo/<instance>.log`

#### Scenario: Log rotation can be declined at install

- **WHEN** the operator declines the log-rotation prompt
- **THEN** the install plan adds no logrotate commands
