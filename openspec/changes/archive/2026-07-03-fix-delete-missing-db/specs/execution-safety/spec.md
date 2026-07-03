## ADDED Requirements

### Requirement: Graceful recovery from a failed command

When a command in an applied plan fails outside the install flow, the tool SHALL report the failure and return
to the menu rather than terminating with an uncaught error.

#### Scenario: A failed command returns to the menu

- **WHEN** applying a plan (e.g. delete, backup, restore, duplicate, fail2ban, config update, or log rotation)
  raises an error on a failing command
- **THEN** the tool reports the failure and returns to the main menu, keeping the session alive
