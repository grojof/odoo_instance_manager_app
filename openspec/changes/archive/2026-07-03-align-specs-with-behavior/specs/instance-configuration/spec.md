## MODIFIED Requirements

### Requirement: Instance status inspection

The tool SHALL render the instance's expected paths and a detected-state table covering the Linux user, home,
config file, systemd service (existence and active state), DB role, data dir, TLS certificate mode, and
optional database existence.

#### Scenario: Status reflects presence of each resource

- **WHEN** the status view is shown
- **THEN** each checked resource is marked present or missing, the TLS certificate mode is classified
  (self-signed / custom-CA / external / Let's Encrypt / incomplete / not configured), and useful values from
  the Odoo config are displayed when the config file exists

### Requirement: Configuration update with pre-update backup

Updating an existing instance's configuration SHALL first back up the current config, systemd unit, and Nginx
vhosts into a single timestamped directory, then **replay the full Odoo base setup** to regenerate the config
and unit, and optionally regenerate the Nginx vhost.

#### Scenario: Existing files are backed up before regeneration

- **WHEN** the operator updates an instance configuration
- **THEN** the plan copies the current config, unit, and Nginx vhosts into a single
  `/var/backups/<instance>/config_preupdate/<timestamp>/` directory before writing new versions

#### Scenario: Update replays the full base setup

- **WHEN** the configuration update is applied
- **THEN** it runs the same base-setup plan as provisioning (package install, user/dir creation, repo clone if
  absent, venv creation and `pip install -r requirements.txt`), not only a config rewrite

#### Scenario: Autostart state is preserved across update

- **WHEN** the configuration is regenerated
- **THEN** the service autostart choice mirrors whether the service is currently enabled at boot
