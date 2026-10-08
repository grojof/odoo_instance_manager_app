## MODIFIED Requirements

### Requirement: Graceful recovery from a failed command

The tool SHALL report a command that fails outside the install flow, or anything else that goes wrong in an
action (an unreadable file, a host answering unexpectedly), by name, and return to the menu rather than terminate
with a traceback. Ctrl+C during a step SHALL stop the whole step — the shell and everything it
started — and wait for it before returning, so no step keeps running behind the menu. `--help` and `--version`
SHALL answer without root; any other argument is refused.

#### Scenario: A failed command returns to the menu

- **WHEN** applying a plan (e.g. delete, backup, restore, duplicate, fail2ban, config update, or log rotation)
  raises an error on a failing command
- **THEN** the tool reports the failure and returns to the main menu, keeping the session alive

#### Scenario: An unexpected error returns to the menu

- **WHEN** an action raises anything else
- **THEN** the tool names the error and returns to the menu

#### Scenario: Ctrl+C stops the step it interrupts

- **WHEN** the operator presses Ctrl+C while a step runs
- **THEN** the step's process group is terminated (killed if it does not end), and control returns once it has
  ended
