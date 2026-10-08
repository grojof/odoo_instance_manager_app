# data-backup-restore Specification

## Purpose

Move instance data safely: back up an instance's database and/or filestore,
restore a dump and/or filestore into a target, and duplicate an instance's
database (and optionally filestore) from a template. Data operations honor
Odoo's copied-vs-moved semantics (UUID regeneration) and optional neutralization
of the target.

## Requirements

### Requirement: Backup

The tool SHALL back up an instance's database (as a compressed custom-format dump) and/or its filestore (as a
gzipped tar) into the chosen backup directory, using a **single timestamp for the whole operation**, naming
each artifact `<instance>--<db>--<timestamp>`, and writing each artifact **atomically** (a temporary file
promoted only on success). The backup directory SHALL be private to root (`700`) and every artifact SHALL be
written private (`umask 077`): a dump holds password hashes, API keys and mail/payment secrets. The backup
directory SHALL be an absolute, dedicated directory: a shared system directory (`/`, `/tmp`, `/var/backups`,
`/etc`, `/opt/odoo`, …) SHALL be refused, since the tool makes the directory private and prunes in it.

#### Scenario: Database backup produces an atomic timestamped custom dump

- **WHEN** the operator selects a backup that includes the database
- **THEN** the plan runs `pg_dump -Fc` to a temporary file and renames it to
  `<backup_dir>/<instance>--<db>--<timestamp>.dump` only on success, removing the temporary file and failing
  the step otherwise

#### Scenario: Filestore backup archives the resolved filestore path atomically

- **WHEN** the operator selects a backup that includes the filestore
- **THEN** the plan tars the resolved filestore directory to a temporary file and renames it to
  `<backup_dir>/<instance>--<db>--<timestamp>.filestore.tar.gz` only on success; a file that changed while
  being read (GNU tar exit 1) does not fail the archive, any other tar failure does. tar reads as the instance
  user and root writes the archive, so a link the instance planted reaches nothing only root could read

#### Scenario: DB dump and filestore archive share one timestamp

- **WHEN** the operator selects a "DB + Filestore" backup
- **THEN** the `.dump` and `.filestore.tar.gz` names carry the **same** timestamp so the pair can be matched

#### Scenario: Backups are private

- **WHEN** a backup is written
- **THEN** the backup directory is mode `700` and the artifacts are readable by root only

#### Scenario: A shared directory is not a backup directory

- **WHEN** the operator gives `/tmp` or `/var/backups` as the backup directory
- **THEN** the tool refuses it and asks for a dedicated one, such as `/var/backups/<instance>`

### Requirement: Restore

Restoring SHALL create the target database from a selected dump and/or restore a filestore archive, refusing to
clobber an existing target database, and require phrase confirmation before applying. The pre-restore
existence check for the target database is evaluated against the **local** PostgreSQL server. An existing
target filestore SHALL be moved aside, never deleted, and the restored files SHALL belong to the instance user.

#### Scenario: Existing target database blocks restore

- **WHEN** the restore includes the database and the target database already exists
- **THEN** the operation reports the conflict and stops without executing

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
**restricted to its owner** — `CONNECT` revoked from `PUBLIC` and granted to the owning role — so an instance's
database role cannot reach other instances' databases. Local drops SHALL use `dropdb --force`, which closes the
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
- **THEN** the plan revokes `CONNECT` on that database from `PUBLIC` and grants it to the owning role, so other
  instances' roles cannot connect to it

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
requested, apply every rule of the neutralisation catalogue (Odoo's `neutralize.sql` 16.0-19.0, extended to
12.0-19.0 and the OCA modules it lists), each guarded by the existence of its table and columns, as one statement
that stops the plan on failure, and then verify that nothing can still act on the outside, failing the plan when
something can. On the local server these statements SHALL run as the copy's owner role with
`search_path = public` (`pg_catalog` is still searched first), never as the superuser: a trigger or function the source database carries
then runs with that role's rights. The neutralisation SHALL leave exactly one active outgoing mail server, pointing at a host that
does not resolve, so Odoo never falls back to the `smtp_server` of `odoo.conf`, and SHALL drop production's SMTP
credentials from the copy.

#### Scenario: Copied mode regenerates the database UUID

- **WHEN** the operator selects the copied mode
- **THEN** the plan writes a fresh `database.uuid`, `database.secret` and `database.create_date` into
  `ir_config_parameter` on the target database

#### Scenario: Neutralization deactivates automation in the target

- **WHEN** the operator opts to neutralize the target
- **THEN** the plan deactivates crons (except Odoo's autovacuum and queue_job's cleanup), mail servers (dropping
  their credentials), fetchmail, payment providers, external carriers and their production mode, OAuth
  providers, calendar tokens, webhooks, IAP tokens, EDI/SII/TicketBAI/Peppol production modes and queued jobs,
  points `web.base.url` at the target, adds the mail sink, and sets `database.is_neutralized`

#### Scenario: A failed or incomplete neutralisation stops the plan

- **WHEN** the neutralisation statement fails, or the check finds something that can still act on the outside
- **THEN** the step fails and the plan stops; no step tolerates its own failure

#### Scenario: Code in the copy runs with its owner's rights

- **WHEN** the copied database has a trigger that tries to make its owner a superuser
- **THEN** the trigger fails for lack of privilege, the step fails, and the role is unchanged

#### Scenario: A check that sees no Odoo table fails

- **WHEN** the check runs where the current schema holds no Odoo table (`ir_cron`)
- **THEN** it fails instead of passing because no rule applied

### Requirement: Database name path safety

An operator-entered database name SHALL be a name Odoo's own database manager accepts
(`^[a-zA-Z0-9][a-zA-Z0-9_.-]+$`, at most 63 characters) before it is interpolated into SQL, a shell command or a
filestore path that is created, archived, or deleted. Such a name holds no path separator, quote, `$` or space,
and cannot start with `-` (an option to `createdb`/`dropdb`/`pg_dump`) or `.`.

#### Scenario: Traversal in a database name is refused

- **WHEN** a database name used for backup, restore, scheduled backup, or filestore deletion contains a path
  separator, starts with `.` or `-`, or holds any character outside Odoo's pattern
- **THEN** the operation is refused with a descriptive error and no command is built or executed

### Requirement: Standalone database duplication

The tool SHALL offer a database-only duplication that copies a source database into a target on the **local**
PostgreSQL server, reusing the selectable copy method (fast template copy, or robust
`pg_dump | pg_restore --role` that reassigns ownership), the copied/moved and neutralize migration semantics,
and an optional filestore copy placed under the **current instance's** data directory. It SHALL NOT provision
or modify any instance service, config, or system user. It SHALL validate the source and target database names
as safe, require phrase confirmation, refuse a target database owned by another role than the instance's and a
template copy across roles, and — when the target database already exists — require an explicit overwrite
before dropping and recreating it.

#### Scenario: A database is duplicated with the chosen method and semantics

- **WHEN** the operator duplicates a database
- **THEN** the plan seeds the target from the source using the selected copy method, applies the copied/moved
  and neutralize semantics, optionally copies the filestore, and runs only after the phrase confirmation

#### Scenario: Existing target database requires an explicit overwrite

- **WHEN** the target database already exists and belongs to the instance's role
- **THEN** the tool requires an explicit overwrite confirmation and, only then, drops and recreates it;
  otherwise it cancels without changes

#### Scenario: Another role's database is not overwritten

- **WHEN** the target database exists and belongs to another role
- **THEN** the tool refuses with a descriptive error and builds no plan

#### Scenario: No instance service or config is touched

- **WHEN** the database duplication runs
- **THEN** only database and (optional) filestore operations are planned — no systemd unit, `odoo.conf`, or
  system user is created or modified

### Requirement: Replica runtime follows the source and the version

A replica created by instance duplication SHALL clone the same core as the source (OCB when the source's
checkout comes from OCA's OCB, else official Odoo), SHALL be built with the interpreter the support matrix picks
for its version on this host, and SHALL get its own data dir `/var/lib/odoo/<instance>`.

#### Scenario: An OCB source gives an OCB replica

- **WHEN** the source instance's checkout has OCA's OCB as origin
- **THEN** the replica's base setup clones OCB at the same branch

### Requirement: A copy stays invisible until neutralised

A database seeded on the local server SHALL be owned by `postgres` until its migration semantics are applied, and
only then handed to its role: an Odoo lists only the databases its own role owns, so no cron worker can start on
the copy before it is neutralised. A restore that neutralises SHALL stop the instance's running service before
creating the database and start it again after the neutralisation.

#### Scenario: The copy is handed over after neutralisation

- **WHEN** a database is duplicated
- **THEN** it is created by postgres, neutralised, and only then `ALTER DATABASE … OWNER TO` the target role

#### Scenario: A restore keeps the service stopped meanwhile

- **WHEN** a database is restored with neutralisation while the instance's service runs
- **THEN** the plan stops the service first and starts it again after the check

### Requirement: Neutralisation check

The tool SHALL offer a read-only check of a database that lists, per rule, what can still act on the outside and
whether the mail sink is in place.

#### Scenario: An armed database is reported

- **WHEN** the operator checks a database whose crons or mail servers are active
- **THEN** the tool lists each such rule with its row count and examples, and changes nothing
