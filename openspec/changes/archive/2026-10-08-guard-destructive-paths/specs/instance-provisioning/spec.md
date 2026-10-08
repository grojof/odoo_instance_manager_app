## ADDED Requirements

### Requirement: A new instance takes a free name

An install with Odoo, and a replica, SHALL refuse an instance name that is a system account or service name
(`backup`, `nginx`, `postgres`, `root`, …) or under which the host already has a home, config dir, systemd unit,
Nginx vhost, SSL dir or Linux user, and SHALL ask for the name again, pointing to Manage instances for an
existing instance. The name becomes the instance's Linux user, unit, home and log: taking an existing one would
hand the tool another account or service, and the cleanup of a failed install would remove it.

#### Scenario: An existing instance is not installed over

- **WHEN** the operator types the name of an instance that already exists on the host
- **THEN** the tool reports what exists under that name and asks for another name before any plan is built

#### Scenario: A system name is refused

- **WHEN** the operator types `backup` (whose home is `/var/backups`) or `nginx` as the instance name
- **THEN** the tool refuses it and asks for another name

## MODIFIED Requirements

### Requirement: Odoo base setup

The Odoo base setup SHALL install OS dependencies, create the instance system user and directory layout, clone
the chosen core (official Odoo or OCB) at the requested branch, build a virtualenv with the interpreter chosen
for the version, install pip, wheel, the setuptools the version needs and its requirements, write the instance
config and systemd unit, and register the service.

#### Scenario: Instance directories and user are created

- **WHEN** the base setup runs for a new instance
- **THEN** it creates the system user (if missing), the `/opt/odoo/<instance>` home with `odoo`, `addons-oca`,
  `addons-custom` subdirs, the `/etc/odoo/<instance>` config dir, and the data dir `/var/lib/odoo/<instance>`
  (mode `750`, owned by the instance user), with correct ownership and a `750` config dir

#### Scenario: Each instance owns only its own log

- **WHEN** the base setup prepares the logs
- **THEN** `/var/log/odoo` is `root:root` mode `755`, the instance owns only `/var/log/odoo/<instance>.log`
  (mode `640`), the logs of earlier instances (accounts whose home is `/opt/odoo/<name>`) get their own owner
  back, and the `su` directive leaves this tool's logrotate policies for `/var/log/odoo`, which root rotates

#### Scenario: Odoo repo and venv are prepared

- **WHEN** the base setup runs
- **THEN** it clones the chosen core at the requested branch only if absent, creates the venv with the chosen
  interpreter, installs pip, wheel and the version's setuptools requirement, and installs `requirements.txt`
  (with the version's substitutes)

#### Scenario: Config and unit files are written with restrictive permissions

- **WHEN** the base setup writes the instance config and systemd unit
- **THEN** `<instance>.conf` is written mode `640` owned `root:<instance>`, and the systemd unit is written
  mode `644`, followed by a systemd daemon-reload

#### Scenario: Service autostart is operator-controlled

- **WHEN** the operator opts into service autostart
- **THEN** the plan enables and starts the service; otherwise it explicitly disables autostart and then starts
  the service (running now but not enabled at boot)
