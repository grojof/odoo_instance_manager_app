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
confirmation phrase that names the operation and target instance.

#### Scenario: Correct phrase authorizes execution

- **WHEN** the operator types the exact required phrase (e.g. `ELIMINAR <instance>`, `RESTORE <instance>`, `DUPLICAR <instance>`)
- **THEN** the plan proceeds to execution

#### Scenario: Wrong phrase cancels execution

- **WHEN** the operator types anything other than the exact phrase
- **THEN** the operation is cancelled and nothing is executed

### Requirement: Identifier validation

Instance and PostgreSQL identifiers SHALL be validated against safe patterns before they are used to build any
command or configuration. This applies to **every** flow that acts on an instance — provisioning,
configuration, removal, purge, and duplication — including instances selected or typed manually and
duplication target names.

#### Scenario: Invalid instance name is rejected

- **WHEN** an instance name does not match a lowercase-first `[a-z][a-z0-9_]{0,31}` pattern
- **THEN** validation fails with a descriptive error and the operator is asked to re-enter safe values

#### Scenario: Invalid database user is rejected

- **WHEN** a database user does not match the PostgreSQL identifier pattern `[a-z_][a-z0-9_]{0,62}`
- **THEN** validation fails with a descriptive error before any plan is built

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

When a provisioning run fails **or is interrupted** while applying, the tool SHALL run a best-effort cleanup of
that instance's residues so the operation can be retried cleanly, and SHALL return control to the menu rather
than terminating the program. Whether the cleanup drops the instance DB role is determined by the **install
mode**, not by whether the role was newly created.

#### Scenario: Failed install triggers cleanup

- **WHEN** applying an install plan raises an error partway through
- **THEN** the tool runs cleanup commands (stop/disable/remove service, remove config, home, Nginx vhosts, SSL
  dir, and — in the PostgreSQL-install modes — the instance DB role, even if it pre-existed) with stop-on-error
  disabled

#### Scenario: Odoo-only install never drops the DB role on cleanup

- **WHEN** an Odoo-only install (no PostgreSQL) fails and cleanup runs
- **THEN** the cleanup does not drop the instance DB role, since that mode does not own it

#### Scenario: Interrupted install triggers cleanup

- **WHEN** applying an install plan is interrupted (e.g. Ctrl+C)
- **THEN** the same best-effort cleanup runs before control returns to the menu

#### Scenario: Cleanup returns to the menu

- **WHEN** cleanup finishes after a failed or interrupted install
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

