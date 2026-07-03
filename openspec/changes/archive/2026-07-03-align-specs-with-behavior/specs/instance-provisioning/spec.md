## MODIFIED Requirements

### Requirement: Odoo base setup

The Odoo base setup SHALL install OS dependencies, create the instance system user and directory layout, clone
the Odoo repository at the requested branch, build a virtualenv with requirements, write the instance config
and systemd unit, and register the service.

#### Scenario: Instance directories and user are created

- **WHEN** the base setup runs for a new instance
- **THEN** it creates the system user (if missing), the `/opt/odoo/<instance>` home with `odoo`, `addons-oca`,
  `addons-custom` subdirs, the `/etc/odoo/<instance>` config dir, and `/var/log/odoo`, with correct ownership
  and a `750` config dir

#### Scenario: Odoo repo and venv are prepared

- **WHEN** the base setup runs
- **THEN** it clones `odoo` at the requested branch only if absent, and creates/updates the venv installing
  `requirements.txt`

#### Scenario: Config and unit files are written with restrictive permissions

- **WHEN** the base setup writes the instance config and systemd unit
- **THEN** `<instance>.conf` is written mode `640` owned `root:<instance>`, and the systemd unit is written
  mode `644`, followed by a systemd daemon-reload

#### Scenario: Service autostart is operator-controlled

- **WHEN** the operator opts into service autostart
- **THEN** the plan enables and starts the service; otherwise it explicitly disables autostart and then starts
  the service (running now but not enabled at boot)
