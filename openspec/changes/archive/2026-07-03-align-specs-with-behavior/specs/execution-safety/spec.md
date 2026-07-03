## MODIFIED Requirements

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
