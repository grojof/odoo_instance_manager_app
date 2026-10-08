## MODIFIED Requirements

### Requirement: Virtualenv package installation

The tool SHALL install Python packages into the instance virtualenv either from
a selected requirements file or from an operator-provided package list, running
the venv's pip directly as the instance user (no login shell). Root SHALL only read the requirements file and
pass it on stdin. A typed entry starting with `-` (a pip option such as `--index-url`) SHALL be refused, and a
comma SHALL separate two entries only when a package name follows it, so a version range such as
`babel>=2.14,<3` stays one requirement.

#### Scenario: Install from a requirements file

- **WHEN** the operator selects a requirements file
- **THEN** the plan validates the venv and the file, then installs the requirements into the venv as the instance user and prints the resulting package list

#### Scenario: Install from a manual package list

- **WHEN** the operator provides packages inline and/or one per line
- **THEN** the plan installs the parsed, non-empty package set into the venv as the instance user; if no valid package is found the operation is cancelled

#### Scenario: A typed value is a package, not a shell word or an option

- **WHEN** the operator types `x$(id)`, `--index-url https://…` or `babel>=2.14,<3`
- **THEN** the first is passed to pip as one quoted argument, the second is refused, and the third is one
  requirement
