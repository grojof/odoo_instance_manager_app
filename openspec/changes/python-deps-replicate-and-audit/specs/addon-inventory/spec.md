## ADDED Requirements

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
