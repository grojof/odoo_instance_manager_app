## MODIFIED Requirements

### Requirement: Scoped instance delete

The tool SHALL remove an instance's systemd service, Odoo config, home, Nginx vhosts (available and enabled),
and SSL directory, and MAY additionally drop the database and remove the filestore when the operator opts in.
When a database drop is requested for a database that does not exist, the tool SHALL warn and skip the drop
rather than fail the operation.

#### Scenario: System residues are removed and Nginx reloaded

- **WHEN** the operator deletes an instance
- **THEN** the plan stops and disables the service, removes the unit and reloads systemd, removes the config
  dir, home, both Nginx vhosts, and the SSL dir, then validates and reloads Nginx

#### Scenario: Optional database and filestore removal

- **WHEN** the operator opts to drop the database and/or remove the filestore
- **THEN** the plan adds a `dropdb --if-exists` for the named database and/or an `rm -rf` of the resolved
  filestore path

#### Scenario: Non-existent database is skipped with a warning

- **WHEN** the operator requests dropping a database that is not found with the given credentials (absent or
  unreachable)
- **THEN** the tool warns that the database was not found and omits the drop, continuing with the rest of the
  removal instead of crashing

#### Scenario: Delete is phrase-confirmed

- **WHEN** the delete plan is assembled
- **THEN** it executes only after the operator types the exact `ELIMINAR <instance>` phrase
