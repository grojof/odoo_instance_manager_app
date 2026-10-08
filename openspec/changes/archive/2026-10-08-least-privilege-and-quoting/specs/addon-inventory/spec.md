## MODIFIED Requirements

### Requirement: Optional inventory export

After rendering the inventory, the tool SHALL offer to export it to a single text file at an operator-chosen
path (defaulting under `./reports/`), mirroring the server-audit report export. The exported content reflects
the active installed/all filter. Declining writes nothing. The file SHALL be new (an existing file, or a link in
its place, is refused) and private (`600`): the export runs as root.

#### Scenario: Inventory is exported on request

- **WHEN** the operator opts to export the inventory
- **THEN** the tool writes the rendered grouped tables (with the active filter) to the chosen file, creating
  the parent directory if needed

#### Scenario: Export can be declined

- **WHEN** the operator declines the export
- **THEN** no file is written
