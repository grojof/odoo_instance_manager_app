## MODIFIED Requirements

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
