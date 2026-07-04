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

### Requirement: Python dependency audit

The addon inventory SHALL report the Python packages the instance's addons declare as required — read
reliably from each manifest's `external_dependencies['python']` — and, for each, whether it is **importable in
the instance's virtualenv** (installed vs missing), together with which addons require it. This audit SHALL be
part of the rendered inventory and its export.

#### Scenario: Required Python packages are listed with their install state

- **WHEN** the operator views the addon inventory
- **THEN** the tool collects the `external_dependencies['python']` entries declared by the discovered addons
  and marks each as installed or missing by testing whether it imports in the instance venv, listing which
  addons require it

#### Scenario: Manifests are parsed safely

- **WHEN** a manifest is read for its Python dependencies
- **THEN** it is parsed as a literal (no code execution) and a malformed manifest is skipped without failing
  the inventory

#### Scenario: No declared dependencies is reported plainly

- **WHEN** no discovered addon declares a Python external dependency
- **THEN** the audit reports that there are no additional Python packages required

