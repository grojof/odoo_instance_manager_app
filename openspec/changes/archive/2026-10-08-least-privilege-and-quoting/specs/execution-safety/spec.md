## ADDED Requirements

### Requirement: Host text cannot drive the terminal

Text that comes from the host — database, file and service names, a command's output, values read from files —
SHALL be printed with every control character except tab and newline, and every escape sequence except colour
(SGR), shown as `?`; a command's streamed output keeps its carriage returns. A value the operator types SHALL be
refused when it holds a control character, so a pasted carriage return or escape never reaches `odoo.conf`, a
unit, or a shell line.

#### Scenario: A hostile database name cannot rewrite the screen

- **WHEN** a listed database name, a file name or a step's output holds an OSC or CSI sequence
- **THEN** the sequence is printed inert, and the plan preview shows what will really run

#### Scenario: A typed control character is refused

- **WHEN** the operator types or pastes a value with a carriage return or an escape
- **THEN** the prompt refuses it and asks again

## MODIFIED Requirements

### Requirement: Secrets out of sight

A secret — a database password, the master password, a file holding them — SHALL never be part of a plan step's
command text: it SHALL travel in the step's environment (which only root can read), a libpq client SHALL take
its password from `PGPASSWORD` there, and SQL holding a password SHALL be fed to `psql` on stdin. The plan
preview SHALL show such a step with its secrets masked — also where a secret appears escaped, as in an SQL
literal — and a failed step's error SHALL name the step rather than print its command. SQL that carries a
password inside a dollar-quoted block SHALL use a tag the password does not contain. Database probes SHALL give up connecting after 10 seconds (`PGCONNECT_TIMEOUT`).

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
