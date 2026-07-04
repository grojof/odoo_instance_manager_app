## MODIFIED Requirements

### Requirement: Instance discovery and selection

The tool SHALL discover instances as directories under `/opt/odoo` and let the operator select a detected
instance or type a known name, and SHALL optionally query PostgreSQL to list available databases for
validation, **scoped to the instance's database role** (databases owned by that role or named after it) rather
than every database on the server.

#### Scenario: Detected instances are listed for selection

- **WHEN** the operator enters instance management
- **THEN** directories under `/opt/odoo` are listed for selection, with options to type a name manually or cancel

#### Scenario: Optional database listing is scoped to the instance role

- **WHEN** the operator opts to connect to PostgreSQL during management
- **THEN** the tool lists only the databases owned by the connected instance role (or whose name starts with
  it), letting the operator pick one as the validation target, or reports the connection error without blocking
  management
