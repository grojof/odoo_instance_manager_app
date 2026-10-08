## MODIFIED Requirements

### Requirement: Install modes

The tool SHALL offer three provisioning modes: Odoo only, PostgreSQL only, and
Odoo + PostgreSQL together. When Odoo and PostgreSQL are installed together on one host, they SHALL talk over
loopback and the tool SHALL NOT open PostgreSQL to the network.

#### Scenario: Install Odoo only

- **WHEN** the operator chooses to install an Odoo instance without a database server
- **THEN** the plan ensures the instance's DB role/login, performs the Odoo base setup, and optionally configures Nginx, without installing PostgreSQL

#### Scenario: Install PostgreSQL only

- **WHEN** the operator chooses to install PostgreSQL without Odoo
- **THEN** the plan installs and enables PostgreSQL, ensures the instance role, validates the role login, and optionally opens remote access

#### Scenario: Install Odoo and PostgreSQL together

- **WHEN** the operator chooses the combined install
- **THEN** the plan performs the DB setup without remote access (no `listen_addresses` change, no `pg_hba`
  rule) followed by the Odoo base setup, and optionally configures Nginx

### Requirement: Odoo base setup

The Odoo base setup SHALL install OS dependencies, create the instance system user and directory layout, clone
the chosen core (official Odoo or OCB) at the requested branch, build a virtualenv with the interpreter chosen
for the version, install pip, wheel, the setuptools the version needs and its requirements, write the instance
config and systemd unit, and register the service.

#### Scenario: Instance directories and user are created

- **WHEN** the base setup runs for a new instance
- **THEN** it creates the system user (if missing), the `/opt/odoo/<instance>` home with `odoo`, `addons-oca`,
  `addons-custom` subdirs, the `/etc/odoo/<instance>` config dir, `/var/log/odoo`, and the data dir
  `/var/lib/odoo/<instance>` (mode `750`, owned by the instance user), with correct ownership and a `750`
  config dir

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

## ADDED Requirements

### Requirement: Python interpreter per Odoo version

The tool SHALL know, for each supported Odoo version (12-19), the Python range it accepts — with the evidence
behind each bound (official, or derived from the branch's `requirements.txt`) — and SHALL build the venv with
the host `python3` only when that interpreter can build the version: inside the range; for a version with no
stated maximum, not newer than the interpreter the matrix recommends; and never Python 3.10 for Odoo 16-19,
whose 3.10 row pins a gevent pip cannot build. Otherwise it SHALL install the matrix's interpreter with uv,
pinned to one release and verified against its published SHA-256, into a shared root-owned directory the
instance users can read but not write. The operator SHALL see the range and the choice before the plan.

#### Scenario: An out-of-range host gets uv's interpreter

- **WHEN** Odoo 14 is installed on a host whose `python3` is 3.12
- **THEN** the plan installs the pinned uv (checksum-verified), installs CPython 3.8 with it, and builds the
  venv with that interpreter

#### Scenario: An in-range host interpreter is used

- **WHEN** Odoo 18 is installed on a host whose `python3` is 3.12
- **THEN** the venv is built with the host `python3` and nothing is downloaded

#### Scenario: setuptools follows the version

- **WHEN** the venv is prepared
- **THEN** it installs `setuptools<58` for Odoo <= 13 (`vatnumber` uses `use_2to3`), `setuptools<81` for Odoo
  <= 16 (they import `pkg_resources` at startup), and the current setuptools otherwise

### Requirement: Odoo core choice

The operator SHALL choose, at install, between official Odoo and OCA's OCB (the same branches with backported
fixes); the base setup SHALL clone the chosen repository. Only these two cores SHALL be accepted.

#### Scenario: OCB is cloned from OCA

- **WHEN** the operator chooses OCB
- **THEN** the plan clones `https://github.com/OCA/OCB.git` at the requested branch

### Requirement: Production defaults for a new instance

A new instance's `odoo.conf` SHALL disable demo data for Odoo <= 18 (`without_demo = all`; Odoo 19 loads none
unless asked), and SHALL set `data_dir` to `/var/lib/odoo/<instance>`, outside the instance home. The systemd
unit SHALL follow Odoo's own (`KillMode=mixed`) and start after the network is online and, for a local
database, after PostgreSQL. A failed install's cleanup SHALL remove the new data dir only while it holds no
filestore.

#### Scenario: A production database gets no demo data

- **WHEN** an instance of Odoo 18 or older is configured
- **THEN** its `odoo.conf` holds `without_demo = all`

#### Scenario: The data dir lives outside the home

- **WHEN** a new instance is configured
- **THEN** its `odoo.conf` holds `data_dir = /var/lib/odoo/<instance>`

### Requirement: Unattended package installation

Every `apt-get install` the tool plans SHALL run non-interactively (`DEBIAN_FRONTEND=noninteractive`, keeping
existing configuration files) and SHALL wait for the dpkg lock rather than fail when another apt run holds it.

#### Scenario: A package install cannot stop on a prompt

- **WHEN** a plan installs a package
- **THEN** the command sets `DEBIAN_FRONTEND=noninteractive`, `Dpkg::Options::=--force-confold` and a
  `DPkg::Lock::Timeout`

### Requirement: PostgreSQL version floor

When the tool installs PostgreSQL for an Odoo version whose documentation states a floor, the plan SHALL
check the local server against it and stop with an explanation when the server is older.

#### Scenario: Odoo 19 requires PostgreSQL 13

- **WHEN** PostgreSQL is set up for Odoo 19
- **THEN** the plan checks `server_version_num` is at least 130000 before creating the role
