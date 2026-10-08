## MODIFIED Requirements

### Requirement: Restore

Restoring SHALL create the target database from a selected dump and/or restore a filestore archive, refusing to
clobber an existing target database, and require phrase confirmation before applying. The pre-restore
existence check for the target database is evaluated against the **local** PostgreSQL server. An existing
target filestore SHALL be moved aside, never deleted, and the restored files SHALL belong to the instance user.
When the instance's database is local, the restore SHALL go the way a duplication does: created by postgres,
restored as the instance's role (`--role`), neutralised and handed over in one step, with no service stop. On a
remote server it SHALL create, restore and neutralise in one step that drops the database it created and starts
the service again when any part fails; the service is otherwise started again once the files are restored too.
Comments are not restored (`--no-comments`): a dump's comment on an extension fails for a role that does not own
it.

#### Scenario: Existing target database blocks restore

- **WHEN** the restore includes the database and the target database already exists (other than an unfinished
  copy of this tool)
- **THEN** the operation reports the conflict and stops without executing

#### Scenario: A failed restore leaves no armed copy

- **WHEN** a step of the database restore fails (the dump does not load, the neutralisation fails)
- **THEN** the database the restore created is dropped and, if the service was stopped for it, started again

#### Scenario: Target-database existence check is local-only

- **WHEN** the operator targets a remote database host for the restore
- **THEN** the pre-restore existence check runs against the local server and may not detect a remote
  collision; the subsequent `createdb` still fails safely if the remote target exists

#### Scenario: Existing target filestore requires explicit overwrite

- **WHEN** the restore includes the filestore and the target filestore exists
- **THEN** the operator must confirm overwrite; on confirmation the previous filestore is moved to
  `<filestore>.replaced-<timestamp>` before extracting, otherwise the restore is cancelled

#### Scenario: Restored files belong to the instance user

- **WHEN** a filestore archive is extracted
- **THEN** tar runs as the instance user (root only reads the archive), restores neither the archive's owners
  nor its permission bits, and the plan gives the files to the
  instance user: the whole data dir when it is the instance's own (`/var/lib/odoo/<instance>` or inside its
  home), only that database's filestore when the data dir may be shared

#### Scenario: Restore is phrase-confirmed

- **WHEN** the restore plan is assembled
- **THEN** it executes only after the operator types the exact `RESTORE <instance>` phrase

### Requirement: Duplication

The tool SHALL duplicate a source instance's database — and optionally its filestore — into a target,
end-to-end and existence-aware, requiring phrase confirmation and validating the source and target database
names as safe before using them in SQL. The target instance SHALL differ from the source instance, and the
target database SHALL differ from the source database.

The operator SHALL choose the database copy method: a fast PostgreSQL **template** copy, or a robust
**`pg_dump | pg_restore --no-owner`** that reassigns ownership to the target role. A template copy keeps the
source's role as owner of every table, so the tool SHALL refuse it when the target role differs from the source
database's owner (always the case for a new replica). The template copy SHALL refuse new connections to the
source, terminate its sessions, copy, and reopen the source whatever the outcome.

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
restart — **without** recreating the target's config, service, or system user. It SHALL drop an existing
target database only when that database belongs to the target's own role (read from its `odoo.conf`) and the
operator explicitly confirms the overwrite.

Migration semantics (copied vs moved, neutralize) SHALL apply in both cases, and the duplicated filestore SHALL
be placed under the **target** instance's data directory — the one its configuration names, also for a replica
whose `odoo.conf` is not written yet — and owned by the target system user (the whole data dir when it is the
target's own, only the copied filestore otherwise). A filestore already at the target SHALL be moved aside to
`<filestore>.replaced-<timestamp>`, never deleted, and the copy SHALL run only when the source filestore exists.
A target that is not a whole instance of this tool (home and `odoo.conf`) SHALL be provisioned only under a free
name, and never refreshed. Every database the tool seeds SHALL have its access
**restricted to its owner** — `CONNECT` revoked from `PUBLIC` when it is created, granted to the owning role at
the hand-over, and `CREATE` on `public` taken from `PUBLIC` — so an instance's database role cannot reach other
instances' databases. The database SHALL be copied after the rest of the target (files, and for a replica the
whole instance), in one step that drops it if any part fails. Local drops SHALL use `dropdb --force`, which closes the
database's sessions and refuses new ones in one statement.

#### Scenario: Replica replicates the source venv Python packages

- **WHEN** a replica is provisioned and the operator opts to replicate packages
- **THEN** the plan installs the source venv's packages into the target venv, so the replica has the same addon
  Python dependencies as the source: the source's `pip freeze` runs as the source user, only exact
  `name==version` lines are kept (in a private temporary directory) and shown, the install runs as the target
  user, and the step fails when either fails

#### Scenario: New target is provisioned and seeded as a replica

- **WHEN** the target instance does not exist
- **THEN** the plan creates the target role, runs the same production-hardening prompts as a fresh install with
  auto-suggested non-colliding ports, provisions the target (base setup without starting, optional Nginx),
  seeds the database and filestore from the source with the `pg_dump` copy, and then starts the target service

#### Scenario: Replica domain must not collide with another vhost

- **WHEN** the replica is configured to front Nginx and the chosen domain is already a `server_name` in an
  enabled vhost
- **THEN** the tool rejects it and re-prompts for a different domain, so the replica is reachable

#### Scenario: Existing target is refreshed in place

- **WHEN** the target instance already exists
- **THEN** the plan stops the target service, drops and recreates its database from the source, replaces its
  filestore, applies the migration semantics, and restarts the service without recreating its config or unit

#### Scenario: A database that is not the target's is never dropped

- **WHEN** the target database exists and belongs to a role other than the target's, or the target equals the
  source instance or the source database
- **THEN** the tool refuses with a descriptive error and builds no plan

#### Scenario: Overwriting the target's database is confirmed

- **WHEN** the target database exists and belongs to the target's role
- **THEN** the operator must explicitly confirm that it will be dropped and replaced before the plan is built

#### Scenario: Operator selects the database copy method

- **WHEN** the duplication plan is assembled
- **THEN** the operator chooses a template copy or a `pg_dump | pg_restore --no-owner` copy, and the plan uses
  the selected method, refusing a template copy across roles

#### Scenario: Template copy frees the source; dump copy leaves it untouched

- **WHEN** the template method is chosen
- **THEN** the plan blocks and terminates the source's sessions before the copy and re-enables them afterward
  even on failure; **WHEN** the dump method is chosen, the source is read live without terminating its sessions

#### Scenario: Migration semantics and phrase confirmation

- **WHEN** duplication runs
- **THEN** copied/moved and neutralize semantics are applied to the target and execution proceeds only after
  the operator types the exact `DUPLICATE <source>` phrase for a replica, or `REPLACE <target>` for a refresh,
  whose data it replaces

#### Scenario: Seeded database is restricted to its owner

- **WHEN** the tool seeds a target database
- **THEN** the plan revokes `CONNECT` on that database from `PUBLIC` when it is created and grants it to the
  owning role only at the hand-over, so no role — its own included — connects to it before it is neutralised

#### Scenario: Target data dir is owned by the target user

- **WHEN** the filestore is copied into the target data directory (created as root)
- **THEN** the plan chowns the target's own data directory to the target system user, so Odoo can create its
  `sessions` and `filestore` entries; in a data directory that may be shared, only the copied filestore

#### Scenario: A previous target filestore is moved aside

- **WHEN** the target filestore already exists
- **THEN** it is moved to `<filestore>.replaced-<timestamp>` and the copy lands in the target, not nested in it

#### Scenario: Unsafe database name is rejected

- **WHEN** the source or target database name is not a safe name
- **THEN** the plan is not built and the operation reports the problem instead of interpolating it into SQL

### Requirement: Copied vs moved database semantics

Restore and duplication SHALL apply Odoo migration semantics: in "copied" mode give the target its own
`database.uuid`, `database.secret` and `database.create_date`, as Odoo's own copy does; when neutralisation is
requested, first run Odoo's own neutralisation — the `data/neutralize.sql` of every module installed in the copy
(states `installed`, `to upgrade`, `to remove`), read as the instance user from its addons paths, as Odoo
16.0-19.0's `neutralize` does — then apply every rule of the neutralisation catalogue (Odoo's `neutralize.sql` 16.0-19.0, extended to
12.0-19.0 and the OCA modules it lists), each guarded by the existence of its table and columns, as one statement
that stops the plan on failure, and then verify that nothing can still act on the outside, failing the plan when
something can. On the local server these statements SHALL run as the copy's owner role with
`search_path = public` (`pg_catalog` is still searched first), never as the superuser: a trigger or function the source database carries
then runs with that role's rights. The neutralisation SHALL leave exactly one active outgoing mail server, pointing at a host that
does not resolve and logging in (`login`, never `cli`, which sends through `odoo.conf`), so Odoo never falls back
to the `smtp_server` of `odoo.conf`, and SHALL drop production's SMTP credentials from the copy and point every
other server at that host (12.0-15.0 still send through an archived server a message names).

#### Scenario: Copied mode regenerates the database UUID

- **WHEN** the operator selects the copied mode
- **THEN** the plan writes a fresh `database.uuid`, `database.secret` and `database.create_date` into
  `ir_config_parameter` on the target database

#### Scenario: Neutralization deactivates automation in the target

- **WHEN** the operator opts to neutralize the target
- **THEN** the plan deactivates crons (except Odoo's autovacuum and queue_job's cleanup), mail servers (dropping
  their credentials), fetchmail, payment providers, external carriers and their production mode, OAuth
  providers, calendar tokens (Google and Microsoft, in every table they lived in 12.0-19.0), webhooks, IAP tokens,
  web push keys and devices, cloud storage settings, certificate and SMS passwords, the EDI proxy (its
  14.0-16.0 parameter included), the Spanish SII, TicketBAI and VERI*FACTU of Odoo and OCA, Peppol and the
  Malaysian and Greek EDI, and queued jobs; points `web.base.url` at the target, adds the mail sink, and sets
  `database.is_neutralized`

#### Scenario: A failed or incomplete neutralisation stops the plan

- **WHEN** the neutralisation statement fails, or the check finds something that can still act on the outside
- **THEN** the step fails and the plan stops; no step tolerates its own failure

#### Scenario: Code in the copy runs with its owner's rights

- **WHEN** the copied database has a trigger that tries to make its owner a superuser
- **THEN** the trigger fails for lack of privilege, the step fails, and the role is unchanged

#### Scenario: A check that sees no Odoo table fails

- **WHEN** the check runs where the current schema holds no Odoo table (`ir_cron`)
- **THEN** it fails instead of passing because no rule applied

### Requirement: A copy stays invisible until neutralised

A database seeded on the local server SHALL be owned by `postgres` until its migration semantics are applied, and
only then handed to its role: an Odoo lists only the databases its own role owns, so no cron worker can start on
the copy before it is neutralised, and its role is granted `CONNECT` only then, so one with `db_name` set cannot
connect by name either. Until it is handed over the copy SHALL carry a staging comment, by which a copy an
interrupted run left behind is recognised and may be replaced; any other database owned by postgres is never
taken for one. A restore to a remote server that neutralises SHALL stop the instance's running service before
creating the database and start it again afterwards, whether or not the restore succeeded.

#### Scenario: The copy is handed over after neutralisation

- **WHEN** a database is duplicated
- **THEN** it is created by postgres, neutralised, and only then `ALTER DATABASE … OWNER TO` the target role

#### Scenario: A restore keeps the service stopped meanwhile

- **WHEN** a database is restored to a remote server with neutralisation while the instance's service runs
- **THEN** the plan stops the service first and starts it again after the files, or at once if the restore fails

#### Scenario: An interrupted copy can be replaced

- **WHEN** the target database is a copy this tool left unfinished (owned by postgres, with the staging comment)
- **THEN** a new duplication or restore drops and replaces it instead of refusing

### Requirement: Neutralisation check

The tool SHALL offer a read-only check of a database that lists, per rule, what can still act on the outside,
whether the mail sink is in place, any active `cli` mail server, and, on 14.0-16.0, whether the EDI proxy's demo
parameter is set.

#### Scenario: An armed database is reported

- **WHEN** the operator checks a database whose crons or mail servers are active
- **THEN** the tool lists each such rule with its row count and examples, and changes nothing
