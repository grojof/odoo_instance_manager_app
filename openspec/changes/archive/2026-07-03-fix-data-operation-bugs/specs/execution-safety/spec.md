## MODIFIED Requirements

### Requirement: Automatic cleanup on failed install

When a provisioning run fails **or is interrupted** while applying, the tool SHALL run a best-effort cleanup of
that instance's residues so the operation can be retried cleanly, and SHALL return control to the menu rather
than terminating the program.

#### Scenario: Failed install triggers cleanup

- **WHEN** applying an install plan raises an error partway through
- **THEN** the tool runs cleanup commands (stop/disable/remove service, remove config, home, Nginx vhosts, SSL
  dir, and — when the run created it — the instance DB role) with stop-on-error disabled

#### Scenario: Interrupted install triggers cleanup

- **WHEN** applying an install plan is interrupted (e.g. Ctrl+C)
- **THEN** the same best-effort cleanup runs before control returns to the menu

#### Scenario: Cleanup returns to the menu

- **WHEN** cleanup finishes after a failed or interrupted install
- **THEN** control returns to the menu and the program does not crash with an uncaught exception
