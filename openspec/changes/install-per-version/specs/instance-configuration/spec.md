## REMOVED Requirements

### Requirement: Configuration update with pre-update backup

**Reason**: replaying the full base setup re-ran apt and pip (moving setuptools under an Odoo that needs it
pinned), replaced `odoo.conf` and lost every key it did not write, started instead of restarting the service so
nothing took effect, and changed the DB password only in the file.

**Migration**: replaced by "Configuration update merges and applies".

## ADDED Requirements

### Requirement: Configuration update merges and applies

Updating an existing instance's configuration SHALL first back up the current config, systemd unit, and Nginx
vhosts into a single private timestamped directory, then rewrite `odoo.conf` **merged** with the current one and
rewrite the unit — without reinstalling anything — and optionally regenerate the Nginx vhost. The keys an
operator tunes by hand (`addons_path`, `data_dir`, `logfile`, `http_interface`, `without_demo`) SHALL keep their
current value, and keys the tool does not write SHALL be carried over. The Odoo version SHALL be read from the
instance's checkout and the domain from its vhost. A new DB password SHALL be set on the local role as well; a
running service SHALL be restarted so the change is live.

#### Scenario: Existing files are backed up before regeneration

- **WHEN** the operator updates an instance configuration
- **THEN** the plan copies the current config, unit, and Nginx vhosts into a single
  `/var/backups/<instance>/config_preupdate/<timestamp>/` directory (mode `700`) before writing new versions

#### Scenario: The current configuration is merged, not replaced

- **WHEN** the current `odoo.conf` holds `data_dir`, extra `addons_path` entries, `smtp_*` or other keys
- **THEN** the rewritten file keeps them

#### Scenario: Nothing is reinstalled

- **WHEN** the configuration update is applied
- **THEN** the plan runs no package install, clone or `pip install`

#### Scenario: The change is live when the plan ends

- **WHEN** the service is running
- **THEN** the plan restarts it after writing the configuration; and when a new DB password was entered for a
  local database, the plan sets it on the role before the restart

#### Scenario: Autostart state is preserved across update

- **WHEN** the configuration is regenerated
- **THEN** the service's enabled-at-boot state is left as it was
