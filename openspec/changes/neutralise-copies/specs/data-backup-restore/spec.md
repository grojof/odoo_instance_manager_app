## MODIFIED Requirements

### Requirement: Copied vs moved database semantics

Restore and duplication SHALL apply Odoo migration semantics: in "copied" mode give the target its own
`database.uuid`, `database.secret` and `database.create_date`, as Odoo's own copy does; when neutralisation is
requested, apply every rule of the neutralisation catalogue (Odoo's `neutralize.sql` 16.0-19.0, extended to
12.0-19.0 and the OCA modules it lists), each guarded by the existence of its table and columns, as one statement
that stops the plan on failure, and then verify that nothing can still act on the outside, failing the plan when
something can. The neutralisation SHALL leave exactly one active outgoing mail server, pointing at a host that
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

## ADDED Requirements

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
