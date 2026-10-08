## MODIFIED Requirements

### Requirement: Database role provisioning

The tool SHALL ensure the instance's PostgreSQL role exists with LOGIN and CREATEDB, creating it only if missing,
storing every password it sets as `scram-sha-256` (the `pg_hba` rule it writes requires it, and PostgreSQL 13
stores md5 by default), and SHALL validate the role can log in with the SSL mode `odoo.conf` sets. When a local
role exists already, the operator SHALL choose: set it to the password entered, or keep its password and type
it, so `odoo.conf` holds the role's real password. Local `psql` SHALL name the instance's port.

#### Scenario: Missing local role is created

- **WHEN** the DB host is local and the role does not exist
- **THEN** the plan creates the role with LOGIN CREATEDB using the configured password, stored as scram

#### Scenario: An existing role keeps or gets the password, as chosen

- **WHEN** the role already exists
- **THEN** the plan re-asserts LOGIN CREATEDB and either sets the entered password (when the operator chose to)
  or leaves the password alone, the operator having typed it for `odoo.conf`

#### Scenario: Remote DB host skips role creation

- **WHEN** the DB host is remote
- **THEN** the plan skips role creation (no admin credentials assumed) and only validates the configured user's
  login, with the SSL mode and, for `verify-*`, the CA at the instance user's `~/.postgresql/root.crt`

### Requirement: Remote database access

When installing PostgreSQL with remote access enabled, the plan SHALL set `listen_addresses = '*'` with
`ALTER SYSTEM` (which a distribution's `conf.d` file does not override), restart PostgreSQL only when the value
changes, read the value back, append a host-scoped `pg_hba` rule for the app server IP using `scram-sha-256`,
and reload PostgreSQL for it.

#### Scenario: Remote access is opened for the app server

- **WHEN** remote access is enabled during a DB install
- **THEN** the plan sets `listen_addresses = '*'` (restarting once if it changed), ensures a `pg_hba` line for
  `<db_user> <app_server_ip>/32 scram-sha-256` (idempotently), and reloads PostgreSQL

#### Scenario: A second run restarts nothing

- **WHEN** the same plan runs again
- **THEN** PostgreSQL is not restarted and the `pg_hba` rule is not added twice

### Requirement: Python interpreter per Odoo version

The tool SHALL know, for each supported Odoo version (12-19), the Python range it accepts — with the evidence
behind each bound (official: Odoo 15-19 state `MIN_PY_VERSION`/`MAX_PY_VERSION`; or derived from the branch's
`requirements.txt`) — and SHALL build the venv with the host `python3` only when that interpreter can build the
version: inside the range; for a version with no stated maximum, not newer than the interpreter the matrix
recommends; and never an interpreter the branch pins `gevent==21.8.0` for (14: above 3.9; 15: 3.10 and 3.11;
16-19: 3.10), which has no wheel for it and whose source no longer builds. uv SHALL be called by the absolute
path the tool installs it at, its version checked, and its interpreters installed without links in root's
PATH. Otherwise it SHALL install the matrix's interpreter with uv,
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
  <= 16 (they import `pkg_resources` at startup, which setuptools 82 removed), and the current setuptools
  otherwise

#### Scenario: A gevent 21.8.0 row is avoided

- **WHEN** Odoo 15 is installed on a host whose `python3` is 3.11 (Debian 12), or Odoo 16 on 3.13 (Debian 13)
- **THEN** the venv is built with uv's 3.12

### Requirement: Optional wkhtmltopdf provisioning

During provisioning the tool SHALL offer to install `wkhtmltopdf`, explaining that Odoo's PDF reports
(invoices, quotations, and similar) require it. The recommended option SHALL install the Qt-patched
0.12.6 build selected for the detected OS codename and machine (`x86_64`, `aarch64`) from a pinned table
(asset URL + SHA-256), verified by checksum before installation; the tool SHALL also offer the distribution
package as a clearly labelled reduced-fidelity fallback when the distribution has one, and a skip option. When the operator skips, the tool SHALL warn
that PDF report generation will fail until wkhtmltopdf is installed.

#### Scenario: Operator is offered wkhtmltopdf with the reports rationale

- **WHEN** the operator provisions an Odoo instance
- **THEN** the tool offers to install wkhtmltopdf and states that PDF reports require it

#### Scenario: Recommended install uses the checksum-verified patched build for the codename

- **WHEN** the operator accepts the recommended wkhtmltopdf option
- **THEN** the plan selects the patched 0.12.6 asset mapped to the detected OS codename (or the closest
  ABI-compatible build when the codename has no native asset), downloads it into a private temporary
  directory, and installs it only if its SHA-256 matches the pinned checksum, in the same step

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

#### Scenario: A PostgreSQL older than the version's floor is refused

- **WHEN** the local server is older than the Odoo version's floor (12, or 13 for Odoo 19 — all of which store
  `scram-sha-256`)
- **THEN** the plan stops before creating the role

#### Scenario: nginx not installed yet

- **WHEN** the plan installs nginx, so none is there while the vhost is rendered
- **THEN** the vhost is written for the version apt would install, or for an older nginx when that is unknown
