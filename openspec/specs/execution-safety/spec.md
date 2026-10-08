# execution-safety Specification

## Purpose

Cross-cutting safety controls that every system-mutating action in the manager
MUST pass through: privilege enforcement, a preview-before-apply gate, explicit
confirmation for sensitive operations, strict identifier validation, automatic
port allocation, and best-effort cleanup when a provisioning run fails partway.

## Requirements

### Requirement: Root privilege enforcement

The tool SHALL require root privileges to run, and SHALL re-check for root
before applying any plan that mutates the system.

#### Scenario: Non-root launch is refused

- **WHEN** the program is started by a user whose effective UID is not 0
- **THEN** it prints guidance to re-run with `sudo` and exits with a non-zero status without showing the menu

#### Scenario: Apply re-checks root

- **WHEN** a plan is confirmed for execution while the effective UID is not 0
- **THEN** the apply step raises an error and no command in the plan is executed

### Requirement: Plan preview before apply

Every action that mutates the system SHALL build an ordered list of commands and present it to the operator
before any command runs. During application, each command's output SHALL be streamed live so long-running
steps are not silent.

#### Scenario: Operator sees the plan and confirms

- **WHEN** an action has assembled its command plan
- **THEN** the tool renders each command with an index and description, and asks the operator to confirm or
  cancel before executing

#### Scenario: Cancelling aborts execution

- **WHEN** the operator declines the confirmation prompt
- **THEN** no command is executed and control returns to the menu

#### Scenario: Empty plan is a no-op

- **WHEN** an action produces no commands
- **THEN** the tool reports that there is nothing to run and executes nothing

#### Scenario: Applied commands stream their output live

- **WHEN** a confirmed plan is applied
- **THEN** each command's combined stdout/stderr is forwarded to the screen as it is produced (not only after
  the command finishes), and a non-zero exit still stops the plan when stop-on-error is set

### Requirement: Phrase confirmation for sensitive actions

Destructive or data-altering actions SHALL require the operator to type an exact
confirmation phrase that names the operation and target instance. The phrases are English, like the rest of
the canonical interface.

#### Scenario: Correct phrase authorizes execution

- **WHEN** the operator types the exact required phrase (e.g. `DELETE <instance>`, `DELETE-ALL <instance>`,
  `RESTORE <instance>`, `DUPLICATE <instance>`)
- **THEN** the plan proceeds to execution

#### Scenario: Wrong phrase cancels execution

- **WHEN** the operator types anything other than the exact phrase
- **THEN** the operation is cancelled and nothing is executed

### Requirement: Identifier validation

Every operator value SHALL be validated against a safe pattern before it is used to build any command or
configuration — instance and PostgreSQL identifiers, and every other value that reaches a shell command, SQL or
a configuration file. This applies to **every** flow that acts on an instance — provisioning, configuration, removal,
purge, backup, restore, and duplication — including instances selected or typed manually and duplication target
names. The values are: the instance name, the database user, the Odoo version, the repo branch, the public
domain, the DB host, the app-server IP, and every database name (Odoo's own `DBNAME_PATTERN`,
`^[a-zA-Z0-9][a-zA-Z0-9_.-]+$`, at most 63 characters). Prompts SHALL ask again when a value is refused.
Existence probes, which run before any plan is previewed, SHALL quote the value they receive.

#### Scenario: Invalid instance name is rejected

- **WHEN** an instance name does not match a lowercase-first `[a-z][a-z0-9_]{0,31}` pattern
- **THEN** validation fails with a descriptive error and the operator is asked to re-enter safe values

#### Scenario: Invalid database user is rejected

- **WHEN** a database user does not match the PostgreSQL identifier pattern `[a-z_][a-z0-9_]{0,62}`
- **THEN** validation fails with a descriptive error before any plan is built

#### Scenario: A value that could break out of a shell word is refused

- **WHEN** the operator enters a repo branch, domain, DB host, app-server IP or database name containing a
  quote, `$`, a backtick, a space, a `;` or a leading `-`
- **THEN** the prompt refuses it with a descriptive error and asks again, and no command is built from it

#### Scenario: Probes quote their argument

- **WHEN** an existence probe (path, user, service, database, role) runs before a plan is previewed
- **THEN** the value is passed as one quoted shell word or one escaped SQL literal

#### Scenario: Manually selected instance is validated before any destructive plan

- **WHEN** an instance name is typed or selected for the manage, delete, or total-purge flows
- **THEN** the name is validated against the instance pattern before any command or SQL is built, and an
  invalid name is refused with a descriptive error and no plan is executed

#### Scenario: Duplication target name is validated

- **WHEN** a target instance and database name are entered for duplication
- **THEN** both are validated against the instance/PostgreSQL patterns before any command or SQL is built, and
  an invalid target is refused with a descriptive error

### Requirement: Automatic port allocation

When collecting an instance configuration, the tool SHALL suggest HTTP and
gevent ports that avoid ports already in use by active listeners, existing Odoo
configs, or existing Nginx vhosts.

#### Scenario: Suggested ports avoid reserved ports

- **WHEN** the operator is prompted for the internal HTTP and gevent ports
- **THEN** the defaults offered are the first pair (preserving the base gevent/HTTP offset) not present in the union of active-listener, Odoo-config, and Nginx-config ports

### Requirement: Automatic cleanup on failed install

When a provisioning run fails **or is interrupted while applying**, the tool SHALL preview a cleanup of what that
run made, ask whether to apply it (default yes), and return control to the menu rather than terminate the
program. Cancelling or interrupting at the plan confirmation SHALL change nothing and run no cleanup. Because a
new instance takes a name with nothing on the host under it, the cleanup removes the instance's unit, config,
home, Nginx vhosts, SSL dir, log, logrotate policy and Linux user; it SHALL remove the data dir only when the
run created it and SHALL drop the DB role only when the role did not exist before the run (unknown counts as
existing). A PostgreSQL-only install SHALL clean up its role only.

#### Scenario: Failed install offers the cleanup of what it made

- **WHEN** applying an install plan raises an error partway through
- **THEN** the tool previews the cleanup steps, asks whether to apply them, and applies them with stop-on-error
  disabled when the operator agrees

#### Scenario: Interrupted install offers the same cleanup

- **WHEN** applying an install plan is interrupted (e.g. Ctrl+C)
- **THEN** the same cleanup is previewed and offered before control returns to the menu

#### Scenario: Nothing is undone before anything ran

- **WHEN** the operator cancels, or presses Ctrl+C, at the plan confirmation
- **THEN** no command runs, no cleanup runs, and the host is left as it was

#### Scenario: What existed before the run is kept

- **WHEN** the data dir or the DB role already existed when the install started, or the role's existence could
  not be checked
- **THEN** the cleanup neither removes that data dir nor drops that role

#### Scenario: A PostgreSQL-only install touches no Odoo artifact

- **WHEN** a database-only install fails
- **THEN** the cleanup drops only the role it created, and touches no unit, home, config or vhost

#### Scenario: Cleanup returns to the menu

- **WHEN** cleanup finishes, or is declined, after a failed or interrupted install
- **THEN** control returns to the menu and the program does not crash with an uncaught exception

### Requirement: Secret input is not echoed

Password prompts that have no visible default SHALL read the secret without echoing it to the screen.

#### Scenario: DB and admin passwords are read without echo

- **WHEN** the operator is prompted for a DB password (backup/restore/duplicate/delete, or DB listing) or the
  purge admin password
- **THEN** the input is read via a no-echo prompt so the password is not displayed as it is typed

### Requirement: Graceful recovery from a failed command

When a command in an applied plan fails outside the install flow, the tool SHALL report the failure and return
to the menu rather than terminating with an uncaught error.

#### Scenario: A failed command returns to the menu

- **WHEN** applying a plan (e.g. delete, backup, restore, duplicate, fail2ban, config update, or log rotation)
  raises an error on a failing command
- **THEN** the tool reports the failure and returns to the main menu, keeping the session alive

### Requirement: Host text cannot drive the terminal

The tool SHALL print text that comes from the host (database, file and service names, a command's output,
values read from files) with every control character except tab and newline, and every escape sequence except
colour (SGR), shown as `?`; a command's streamed output keeps its carriage returns. A value the operator types SHALL be
refused when it holds a control character, so a pasted carriage return or escape never reaches `odoo.conf`, a
unit, or a shell line.

#### Scenario: A hostile database name cannot rewrite the screen

- **WHEN** a listed database name, a file name or a step's output holds an OSC or CSI sequence
- **THEN** the sequence is printed inert, and the plan preview shows what will really run

#### Scenario: A typed control character is refused

- **WHEN** the operator types or pastes a value with a carriage return or an escape
- **THEN** the prompt refuses it and asks again

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
