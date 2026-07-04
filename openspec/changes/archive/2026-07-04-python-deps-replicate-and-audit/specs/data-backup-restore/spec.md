## MODIFIED Requirements

### Requirement: Duplication

The tool SHALL duplicate a source instance's database — and optionally its filestore — into a target,
end-to-end and existence-aware, requiring phrase confirmation and validating the source and target database
names as safe before using them in SQL.

The operator SHALL choose the database copy method: a fast PostgreSQL **template** copy (frees the source of
sessions first, best when the target uses the same role), or a robust **`pg_dump | pg_restore --no-owner`**
that reassigns ownership to the target role (correct for a cross-user target such as production→development).

When the **target instance does not exist**, duplication SHALL provision it fully before seeding: create the
target role, run the base setup (system user, home, Odoo checkout at the source's version, virtualenv,
`odoo.conf`, systemd unit) **without starting the service**, optionally configure Nginx, seed the database and
filestore, then start the service. The replica SHALL follow the **same production-hardening prompts as a fresh
install** (secrets with informed choice, `list_db`, `dbfilter`, worker sizing, `db_sslmode`, wkhtmltopdf) with
auto-suggested non-colliding internal ports, and — when it fronts Nginx — SHALL require a domain that is **not
already served by another vhost** (or the replica would be unreachable behind a shared `server_name`). It SHALL
also offer to **replicate the source venv's Python packages** into the target venv, so addon dependencies the
source installed beyond `requirements.txt` are present in the replica.

When the **target instance already exists**, duplication SHALL refresh it in place: stop the target service,
drop and recreate its database from the source and replace its filestore, apply the migration semantics, and
restart — **without** recreating the target's config, service, or system user.

Migration semantics (copied vs moved, neutralize) SHALL apply in both cases, and the duplicated filestore SHALL
be placed under the **target** instance's data directory, which SHALL be owned by the target system user (so
Odoo can create its `sessions`/`filestore` entries). Every database the tool seeds SHALL have its access
**restricted to its owner** — `CONNECT` revoked from `PUBLIC` and granted to the owning role — so an instance's
database role cannot reach other instances' databases.

#### Scenario: Replica replicates the source venv Python packages

- **WHEN** a replica is provisioned and the operator opts to replicate packages
- **THEN** the plan installs the source venv's packages (a filtered `pip freeze`) into the target venv, so the
  replica has the same addon Python dependencies as the source

#### Scenario: New target is provisioned and seeded as a replica

- **WHEN** the target instance does not exist
- **THEN** the plan creates the target role, runs the same production-hardening prompts as a fresh install with
  auto-suggested non-colliding ports, provisions the target (base setup without starting, optional Nginx),
  seeds the database and filestore from the source, and then starts the target service

#### Scenario: Replica domain must not collide with another vhost

- **WHEN** the replica is configured to front Nginx and the chosen domain is already a `server_name` in an
  enabled vhost
- **THEN** the tool rejects it and re-prompts for a different domain, so the replica is reachable

#### Scenario: Existing target is refreshed in place

- **WHEN** the target instance already exists
- **THEN** the plan stops the target service, drops and recreates its database from the source, replaces its
  filestore, applies the migration semantics, and restarts the service without recreating its config or unit

#### Scenario: Operator selects the database copy method

- **WHEN** the duplication plan is assembled
- **THEN** the operator chooses a template copy or a `pg_dump | pg_restore --no-owner` copy, and the plan uses
  the selected method

#### Scenario: Template copy frees the source; dump copy leaves it untouched

- **WHEN** the template method is chosen
- **THEN** the plan blocks and terminates the source's sessions before the copy and re-enables them afterward
  even on failure; **WHEN** the dump method is chosen, the source is read live without terminating its sessions

#### Scenario: Migration semantics and phrase confirmation

- **WHEN** duplication runs
- **THEN** copied/moved and neutralize semantics are applied to the target and execution proceeds only after
  the operator types the exact `DUPLICAR <instance>` phrase

#### Scenario: Seeded database is restricted to its owner

- **WHEN** the tool seeds a target database
- **THEN** the plan revokes `CONNECT` on that database from `PUBLIC` and grants it to the owning role, so other
  instances' roles cannot connect to it

#### Scenario: Target data dir is owned by the target user

- **WHEN** the filestore is copied into the target data directory (created as root)
- **THEN** the plan chowns the whole target data directory to the target system user, so Odoo can create its
  `sessions` and `filestore` entries

#### Scenario: Unsafe database name is rejected

- **WHEN** the source or target database name is not a safe name
- **THEN** the plan is not built and the operation reports the problem instead of interpolating it into SQL
