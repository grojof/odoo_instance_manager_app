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

Every action that mutates the system SHALL build an ordered list of commands and
present it to the operator before any command runs.

#### Scenario: Operator sees the plan and confirms

- **WHEN** an action has assembled its command plan
- **THEN** the tool renders each command with an index and description, and asks the operator to confirm or cancel before executing

#### Scenario: Cancelling aborts execution

- **WHEN** the operator declines the confirmation prompt
- **THEN** no command is executed and control returns to the menu

#### Scenario: Empty plan is a no-op

- **WHEN** an action produces no commands
- **THEN** the tool reports that there is nothing to run and executes nothing

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

Instance and PostgreSQL identifiers SHALL be validated against safe patterns
before they are used to build any command or configuration.

#### Scenario: Invalid instance name is rejected

- **WHEN** an instance name does not match a lowercase-first `[a-z][a-z0-9_]{0,31}` pattern
- **THEN** validation fails with a descriptive error and the operator is asked to re-enter safe values

#### Scenario: Invalid database user is rejected

- **WHEN** a database user does not match the PostgreSQL identifier pattern `[a-z_][a-z0-9_]{0,62}`
- **THEN** validation fails with a descriptive error before any plan is built

### Requirement: Automatic port allocation

When collecting an instance configuration, the tool SHALL suggest HTTP and
gevent ports that avoid ports already in use by active listeners, existing Odoo
configs, or existing Nginx vhosts.

#### Scenario: Suggested ports avoid reserved ports

- **WHEN** the operator is prompted for the internal HTTP and gevent ports
- **THEN** the defaults offered are the first pair (preserving the base gevent/HTTP offset) not present in the union of active-listener, Odoo-config, and Nginx-config ports

### Requirement: Automatic cleanup on failed install

When a provisioning run fails while applying, the tool SHALL run a best-effort
cleanup of that instance's residues so the operation can be retried cleanly.

#### Scenario: Failed install triggers cleanup

- **WHEN** applying an install plan raises an error partway through
- **THEN** the tool runs cleanup commands (stop/disable/remove service, remove config, home, Nginx vhosts, SSL dir, and — when the run created it — the instance DB role) with stop-on-error disabled, then re-raises the failure
