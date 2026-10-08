## ADDED Requirements

### Requirement: Secrets out of sight

A secret — a database password, the master password, a file holding them — SHALL never be part of a plan step's
command text: it SHALL travel in the step's environment (which only root can read), a libpq client SHALL take
its password from `PGPASSWORD` there, and SQL holding a password SHALL be fed to `psql` on stdin. The plan
preview SHALL show such a step with its secrets masked, and a failed step's error SHALL name the step rather than
print its command. Database probes SHALL give up connecting after 10 seconds (`PGCONNECT_TIMEOUT`).

#### Scenario: A password is not visible to other users while a step runs

- **WHEN** a step connects to PostgreSQL with a password
- **THEN** the password is in the step's environment and in no process's arguments

#### Scenario: The preview masks secrets

- **WHEN** the plan writes `odoo.conf` or sets a role's password
- **THEN** the preview shows the file or statement with `admin_passwd`, `db_password` and the role password as
  `********`

#### Scenario: Files are written atomically

- **WHEN** a plan writes a file
- **THEN** it writes a private temporary file in the same directory, sets the mode, and renames it over the
  target, so the file is never seen half-written or with a wider mode

#### Scenario: A failure does not print the command

- **WHEN** a step fails
- **THEN** the error names the step's description
