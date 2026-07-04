# addon-inventory Specification

## Purpose
TBD - created by archiving change add-addon-inventory. Update Purpose after archive.
## Requirements
### Requirement: Addon inventory by origin

The tool SHALL list an instance's addon modules grouped by origin (Odoo core, OCA, custom, and any other
addons-path root), each with the module's manifest version, read from the instance's `addons_path`.

#### Scenario: Available modules are listed per origin with versions

- **WHEN** the operator views the addon inventory for an instance
- **THEN** the tool discovers module directories (those with a `__manifest__.py`/`__openerp__.py`) under each
  addons-path root, groups them as Odoo core / OCA / Custom / other, and shows each module with its manifest
  version

### Requirement: Installed-state enrichment

When the operator opts to check installed modules against a chosen database, the tool SHALL mark which modules
are installed and their installed version, read from `ir_module_module`, and SHALL let the operator choose to
list **only installed** modules or **all** discovered modules.

#### Scenario: Installed modules are marked when a database is checked

- **WHEN** the operator opts to check installed modules and provides a database and credentials
- **THEN** each listed module shows its `ir_module_module` state and installed version, and a failed
  connection degrades gracefully to showing only the available modules

#### Scenario: Operator can list only installed modules

- **WHEN** a database has been checked and the operator chooses to show only installed modules
- **THEN** the inventory lists only modules whose `ir_module_module` state is installed, hiding
  not-installed modules and any origin group left empty

### Requirement: Optional inventory export

After rendering the inventory, the tool SHALL offer to export it to a single text file at an operator-chosen
path (defaulting under `./reports/`), mirroring the server-audit report export. The exported content reflects
the active installed/all filter. Declining writes nothing.

#### Scenario: Inventory is exported on request

- **WHEN** the operator opts to export the inventory
- **THEN** the tool writes the rendered grouped tables (with the active filter) to the chosen file, creating
  the parent directory if needed

#### Scenario: Export can be declined

- **WHEN** the operator declines the export
- **THEN** no file is written

