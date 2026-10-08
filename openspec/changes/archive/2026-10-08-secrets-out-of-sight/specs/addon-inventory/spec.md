## ADDED Requirements

### Requirement: Python dependencies checked the way Odoo checks them

The addon inventory SHALL report a declared Python dependency as present when the instance venv has a
distribution of that name, or else can import a module of that name — Odoo's own order
(`check_python_external_dependency`) — so a dependency declared by its distribution name (`python-stdnum`,
`pdfminer.six`) is not reported missing.

#### Scenario: A distribution name is found

- **WHEN** an addon declares `python-stdnum` and the venv has that distribution
- **THEN** the inventory reports it present
