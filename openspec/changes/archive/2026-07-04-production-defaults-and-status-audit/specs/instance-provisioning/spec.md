## MODIFIED Requirements

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

## ADDED Requirements

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
