## MODIFIED Requirements

### Requirement: Identifier validation

Instance and PostgreSQL identifiers SHALL be validated against safe patterns before they are used to build any
command or configuration. This applies to **every** flow that acts on an instance — provisioning,
configuration, removal, purge, and duplication — including instances selected or typed manually and
duplication target names.

#### Scenario: Invalid instance name is rejected

- **WHEN** an instance name does not match a lowercase-first `[a-z][a-z0-9_]{0,31}` pattern
- **THEN** validation fails with a descriptive error and the operator is asked to re-enter safe values

#### Scenario: Invalid database user is rejected

- **WHEN** a database user does not match the PostgreSQL identifier pattern `[a-z_][a-z0-9_]{0,62}`
- **THEN** validation fails with a descriptive error before any plan is built

#### Scenario: Manually selected instance is validated before any destructive plan

- **WHEN** an instance name is typed or selected for the manage, delete, or total-purge flows
- **THEN** the name is validated against the instance pattern before any command or SQL is built, and an
  invalid name is refused with a descriptive error and no plan is executed

#### Scenario: Duplication target name is validated

- **WHEN** a target instance and database name are entered for duplication
- **THEN** both are validated against the instance/PostgreSQL patterns before any command or SQL is built, and
  an invalid target is refused with a descriptive error
