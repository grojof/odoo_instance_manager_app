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
are installed and their installed version, read from `ir_module_module`.

#### Scenario: Installed modules are marked when a database is checked

- **WHEN** the operator opts to check installed modules and provides a database and credentials
- **THEN** each listed module shows its `ir_module_module` state and installed version, and a failed
  connection degrades gracefully to showing only the available modules

