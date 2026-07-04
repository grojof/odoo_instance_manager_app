## MODIFIED Requirements

### Requirement: Duplication

The tool SHALL duplicate a source database into a new target using PostgreSQL template copy, refusing to
overwrite an existing target instance, service, database, or filestore, and require phrase confirmation.
Because a template copy requires no other sessions on the source database, the tool SHALL prepare the source
for the copy without the operator stopping the service: block new connections to the source, terminate its
existing sessions, run the template copy, and **re-enable connections to the source afterward even if the copy
fails**. It SHALL operate with the instance's own database role (no superuser assumed) and validate the source
database name as safe before using it in SQL. The duplicated filestore SHALL be placed under the **target**
instance's data directory. Duplication copies the database and (optionally) the filestore only; it does **not**
provision the target instance's service, config, or system user.

#### Scenario: Pre-existing target resources block duplication

- **WHEN** the target home, systemd service, database, or (when duplicating the filestore) target filestore
  already exists
- **THEN** the operation reports the specific conflict and stops without executing

#### Scenario: Duplication frees the source, copies via template, and is phrase-confirmed

- **WHEN** the duplication plan is assembled
- **THEN** it blocks new connections to the source database, terminates its existing sessions, creates the
  target with `createdb -T <source>` (optionally copying the filestore), and runs only after the operator types
  the exact `DUPLICAR <instance>` phrase

#### Scenario: Source connections are re-enabled even if the copy fails

- **WHEN** the template-copy step fails after the source was blocked
- **THEN** the plan re-enables connections to the source database regardless, leaving the source reachable

#### Scenario: Unsafe source database name is rejected

- **WHEN** the source database name is not a safe name
- **THEN** the plan is not built and the operation reports the problem instead of interpolating it into SQL

#### Scenario: Duplicated filestore lands under the target instance

- **WHEN** the filestore is duplicated
- **THEN** the copy is written under the target instance's data directory (resolved from the target instance),
  not the source instance's, so the duplicated instance has its attachments

#### Scenario: Duplication does not provision the target instance

- **WHEN** duplication completes
- **THEN** only the database and (optionally) filestore exist for the target; provisioning its service, config,
  and user remains a separate install step
