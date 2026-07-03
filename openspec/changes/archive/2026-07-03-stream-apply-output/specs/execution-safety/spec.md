## MODIFIED Requirements

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
