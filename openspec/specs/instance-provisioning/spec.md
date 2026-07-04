# instance-provisioning Specification

## Purpose

Install and provision Odoo Community instances and their PostgreSQL backing on
an Ubuntu server: an Odoo-only instance, a PostgreSQL-only setup, or both
together. Provisioning is idempotent where possible (create-if-missing) and
always renders a plan before applying.
## Requirements
### Requirement: Install modes

The tool SHALL offer three provisioning modes: Odoo only, PostgreSQL only, and
Odoo + PostgreSQL together.

#### Scenario: Install Odoo only

- **WHEN** the operator chooses to install an Odoo instance without a database server
- **THEN** the plan ensures the instance's DB role/login, performs the Odoo base setup, and optionally configures Nginx, without installing PostgreSQL

#### Scenario: Install PostgreSQL only

- **WHEN** the operator chooses to install PostgreSQL without Odoo
- **THEN** the plan installs and enables PostgreSQL, ensures the instance role, validates the role login, and optionally opens remote access

#### Scenario: Install Odoo and PostgreSQL together

- **WHEN** the operator chooses the combined install
- **THEN** the plan performs the DB setup (with remote access) followed by the Odoo base setup, and optionally configures Nginx

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

### Requirement: Database role provisioning

The tool SHALL ensure the instance's PostgreSQL role exists with LOGIN and
CREATEDB, creating it only if missing and never overwriting the password of an
existing role, and SHALL validate the role can log in.

#### Scenario: Missing local role is created

- **WHEN** the DB host is local and the role does not exist
- **THEN** the plan creates the role with LOGIN CREATEDB using the configured password

#### Scenario: Existing role is preserved

- **WHEN** the role already exists
- **THEN** the plan re-asserts LOGIN CREATEDB but does not change the existing password, emitting a notice that the role is reused

#### Scenario: Remote DB host skips role creation

- **WHEN** the DB host is remote
- **THEN** the plan skips role creation (no admin credentials assumed) and only validates the configured user's login

### Requirement: Remote database access

When installing PostgreSQL with remote access enabled, the plan SHALL set
`listen_addresses='*'` and append a host-scoped `pg_hba` rule for the app
server IP using `scram-sha-256`, then restart PostgreSQL.

#### Scenario: Remote access is opened for the app server

- **WHEN** remote access is enabled during a DB install
- **THEN** the plan edits the resolved `postgresql.conf` for `listen_addresses='*'`, ensures a `pg_hba` line for `<db_user> <app_server_ip>/32 scram-sha-256` (idempotently), and restarts PostgreSQL

### Requirement: Safe configuration defaults

When a required **secret** (DB password or Odoo master/admin password) is left blank, the tool SHALL
default it to a freshly generated strong random value (using the Python standard library) and SHALL
NOT silently fall back to the instance name. The operator MAY still set a weak secret — including the
instance name — but only after an explicit warning describing the risk. The DB **user** (an
identifier, not a secret) MAY continue to default to the instance name.

#### Scenario: Blank secret defaults to a generated strong value

- **WHEN** the operator leaves the DB password or the Odoo master password empty
- **THEN** the tool proposes a freshly generated strong random secret as the accepted-by-default value
  and never substitutes the instance name for a blank secret

#### Scenario: Weak secret requires an acknowledged warning

- **WHEN** the operator sets a secret equal to the instance name or another weak value
- **THEN** the tool warns that the value is guessable and what it exposes (the master password guards
  the database manager) before accepting the choice

#### Scenario: DB user still defaults to the instance name

- **WHEN** the operator leaves the DB user empty
- **THEN** the DB user is set to the instance name during normalization, unchanged from prior behavior

### Requirement: Optional log rotation at install

When provisioning an instance that installs Odoo, the tool SHALL offer to set up system log rotation for the
instance's Odoo log, defaulting to enabled.

#### Scenario: Log rotation is set up by default on install

- **WHEN** the operator provisions an Odoo instance and accepts the (default-yes) log-rotation prompt
- **THEN** the install plan includes a system logrotate policy for `/var/log/odoo/<instance>.log`

#### Scenario: Log rotation can be declined at install

- **WHEN** the operator declines the log-rotation prompt
- **THEN** the install plan adds no logrotate commands

### Requirement: Database manager exposure control

During provisioning the tool SHALL let the operator choose whether the Odoo database manager is
exposed via the `list_db` setting, SHALL recommend `list_db = False` for production as the default,
and SHALL write the chosen value into the instance config. When the operator keeps the manager exposed
(`list_db = True`), the tool SHALL warn that database listing, creation, and deletion become reachable
over HTTP and are guarded only by the master password.

#### Scenario: Recommended default disables the database manager

- **WHEN** the operator provisions an instance and accepts the recommended default
- **THEN** the instance config is written with `list_db = False`

#### Scenario: Keeping the manager exposed requires an acknowledged warning

- **WHEN** the operator chooses to keep `list_db = True`
- **THEN** the tool warns about the HTTP-reachable database manager before writing `list_db = True`
  and notes that a strong master password and a `dbfilter` are then required

### Requirement: Production performance tuning

The tool SHALL derive the Odoo worker configuration from the target host's detected resources rather
than a fixed value: `workers = (detected_cpu * 2) + 1`, sizing `limit_memory_soft`/`limit_memory_hard`
per worker and capping the derived worker count so the combined worker and cron memory budget fits
detected RAM. Resource detection SHALL occur in the execution layer (the pure planners only receive
the computed values), and the operator MAY override the suggested tuning.

#### Scenario: Workers are derived from detected CPU

- **WHEN** the base setup computes the runtime tuning on a host with a detected CPU count
- **THEN** the suggested `workers` equals `(cpu * 2) + 1` and is written to the instance config

#### Scenario: Worker count is capped by available memory

- **WHEN** the derived worker count's memory budget would exceed detected RAM (after an OS/PostgreSQL
  reserve)
- **THEN** the suggested worker count is reduced so the budget fits, with a floor for a production host

#### Scenario: Operator can override the suggested tuning

- **WHEN** the operator is shown the suggested workers and memory limits
- **THEN** the operator can accept the suggestion or supply their own values, which are written instead

#### Scenario: Memory limits scale with the worker count

- **WHEN** the tuning is written
- **THEN** `limit_memory_soft` and `limit_memory_hard` are per-worker sizes and `limit_request` is set

### Requirement: Database filter

The tool SHALL offer to write a `dbfilter` that binds the instance to its database(s), recommending it and
defaulting the suggested value to an exact match on the instance's database name when known (`^<db_name>$`)
or a host-based filter otherwise. The operator MAY decline, in which case **no** `dbfilter` key is written
and Odoo serves all databases. The tool SHALL especially recommend a `dbfilter` when the database manager is
exposed or the Website app is in use.

#### Scenario: A dbfilter is written when the operator opts in

- **WHEN** the operator accepts the recommended dbfilter
- **THEN** a `dbfilter` entry is written to the instance config

#### Scenario: Suggested dbfilter binds to the known database name

- **WHEN** the operator opts in and provided a database name
- **THEN** the suggested `dbfilter` matches that database name exactly (`^<db_name>$`)

#### Scenario: Declining writes no dbfilter

- **WHEN** the operator declines the dbfilter
- **THEN** no `dbfilter` key is written to the instance config and the instance does not filter databases

### Requirement: PostgreSQL SSL mode for remote databases

When the configured database host is remote (not a local socket or loopback address), the tool SHALL
set `db_sslmode` in the instance config, defaulting to `require`, and SHALL let the operator choose a
stricter (`verify-full`) or weaker mode after describing the trade-off. For local database hosts the
tool SHALL NOT force a `db_sslmode`.

#### Scenario: Remote DB host defaults to db_sslmode = require

- **WHEN** the DB host is a remote address
- **THEN** the instance config is written with `db_sslmode = require` unless the operator overrides it

#### Scenario: Local DB host keeps the Odoo default

- **WHEN** the DB host is local (socket or loopback)
- **THEN** no `db_sslmode` key is forced into the instance config

#### Scenario: Operator can select a stricter or weaker SSL mode

- **WHEN** the operator is offered the SSL mode for a remote host
- **THEN** the operator may choose `verify-full` or a weaker mode, and the trade-off is described
  before the choice is written

### Requirement: Optional wkhtmltopdf provisioning

During provisioning the tool SHALL offer to install `wkhtmltopdf`, explaining that Odoo's PDF reports
(invoices, quotations, and similar) require it. The recommended option SHALL install the Qt-patched
0.12.6 build selected for the detected OS codename from a pinned table (asset URL + SHA-256), verified
by checksum before installation; the tool SHALL also offer the distribution package as a clearly
labelled reduced-fidelity fallback, and a skip option. When the operator skips, the tool SHALL warn
that PDF report generation will fail until wkhtmltopdf is installed.

#### Scenario: Operator is offered wkhtmltopdf with the reports rationale

- **WHEN** the operator provisions an Odoo instance
- **THEN** the tool offers to install wkhtmltopdf and states that PDF reports require it

#### Scenario: Recommended install uses the checksum-verified patched build for the codename

- **WHEN** the operator accepts the recommended wkhtmltopdf option
- **THEN** the plan selects the patched 0.12.6 asset mapped to the detected OS codename (or the closest
  ABI-compatible build when the codename has no native asset), downloads it, and installs it only if
  its SHA-256 matches the pinned checksum

#### Scenario: Distribution package is offered as a reduced-fidelity fallback

- **WHEN** the operator chooses the distribution package instead
- **THEN** the plan installs the distro `wkhtmltopdf`, labelled as un-patched/reduced-fidelity

#### Scenario: Unmapped codename avoids guessing a download

- **WHEN** the detected codename has no mapped patched asset and no ABI-compatible fallback
- **THEN** the tool does not fabricate a download URL and instead recommends the distribution package
  or skipping

#### Scenario: Skipping warns that PDF reports will fail

- **WHEN** the operator skips wkhtmltopdf installation
- **THEN** the tool warns that PDF report generation will fail until wkhtmltopdf is installed

### Requirement: Environment detection and version-adaptive configuration

The tool SHALL detect the version-sensitive components of the target host — OS family and codename
(from `/etc/os-release`), the nginx version, and the PostgreSQL version — and combine them with the
operator-supplied Odoo major to render version-correct configuration rather than assuming a fixed
stack. Detection SHALL run in the execution layer (the pure planners receive the resolved values), and
when a component is unknown or unsupported the tool SHALL fall back to the safest known form and report
what it assumed.

#### Scenario: Odoo config key matches the Odoo major

- **WHEN** the instance config is written for a known Odoo major
- **THEN** Odoo ≥ 16 receives `gevent_port` and Odoo ≤ 15 receives `longpolling_port` for the same
  configured port value

#### Scenario: Detection feeds rendering from the execution layer

- **WHEN** the host's OS codename, nginx version, or PostgreSQL version is needed for rendering
- **THEN** it is probed in the execution layer and passed into the planners, which remain free of I/O

#### Scenario: Unsupported OS family is reported, not assumed

- **WHEN** the detected OS is not part of the Debian/Ubuntu (apt) family the package steps target
- **THEN** the tool warns that package installation steps may not apply instead of running them blindly

#### Scenario: PostgreSQL without scram support is flagged

- **WHEN** the detected PostgreSQL version does not support `scram-sha-256` (older than 10)
- **THEN** the tool reports it rather than silently writing an unsupported `pg_hba` auth method

