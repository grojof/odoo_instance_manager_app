## MODIFIED Requirements

### Requirement: Total superuser purge

The tool SHALL provide a total purge that, in addition to the scoped removal, deletes the instance's Linux
user, its Odoo/Nginx logs, the filestore root, all databases discovered for the instance, and the instance's
PostgreSQL roles. Database discovery SHALL find the instance's databases by **owner** (the instance's DB user,
which the tool prompts for) as well as by name prefix, so databases associated with the instance are cleaned
even when their name does not start with the instance name.

#### Scenario: Databases are discovered from filestore, by prefix, and by owner

- **WHEN** the purge collects databases to remove
- **THEN** it gathers filestore-derived database names and, when admin DB access is available, databases whose
  name matches the `<instance>%` prefix **or** that are owned by the instance's DB role (which the operator is
  prompted for), plus any operator-supplied extras

#### Scenario: Admin DB access enables role and database deletion

- **WHEN** admin PostgreSQL access is resolved (local `sudo -u postgres` or validated remote admin credentials)
- **THEN** the plan terminates active connections and drops each candidate database, and drops the instance/db-user roles; without admin access it warns and performs local cleanup only

#### Scenario: Purge shows a summary and is phrase-confirmed

- **WHEN** the purge plan is assembled
- **THEN** it presents a summary of detected resources and executes only after the operator types the exact `ELIMINAR-TODO <instance>` phrase
