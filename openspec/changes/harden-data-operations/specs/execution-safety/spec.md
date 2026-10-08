## MODIFIED Requirements

### Requirement: Identifier validation

Instance and PostgreSQL identifiers, and every other operator value that reaches a shell command, SQL or a
configuration file, SHALL be validated against safe patterns before they are used to build any command or
configuration. This applies to **every** flow that acts on an instance — provisioning, configuration, removal,
purge, backup, restore, and duplication — including instances selected or typed manually and duplication target
names. The values are: the instance name, the database user, the Odoo version, the repo branch, the public
domain, the DB host, the app-server IP, and every database name (Odoo's own `DBNAME_PATTERN`,
`^[a-zA-Z0-9][a-zA-Z0-9_.-]+$`, at most 63 characters). Prompts SHALL ask again when a value is refused.
Existence probes, which run before any plan is previewed, SHALL quote the value they receive.

#### Scenario: Invalid instance name is rejected

- **WHEN** an instance name does not match a lowercase-first `[a-z][a-z0-9_]{0,31}` pattern
- **THEN** validation fails with a descriptive error and the operator is asked to re-enter safe values

#### Scenario: Invalid database user is rejected

- **WHEN** a database user does not match the PostgreSQL identifier pattern `[a-z_][a-z0-9_]{0,62}`
- **THEN** validation fails with a descriptive error before any plan is built

#### Scenario: A value that could break out of a shell word is refused

- **WHEN** the operator enters a repo branch, domain, DB host, app-server IP or database name containing a
  quote, `$`, a backtick, a space, a `;` or a leading `-`
- **THEN** the prompt refuses it with a descriptive error and asks again, and no command is built from it

#### Scenario: Probes quote their argument

- **WHEN** an existence probe (path, user, service, database, role) runs before a plan is previewed
- **THEN** the value is passed as one quoted shell word or one escaped SQL literal

#### Scenario: Manually selected instance is validated before any destructive plan

- **WHEN** an instance name is typed or selected for the manage, delete, or total-purge flows
- **THEN** the name is validated against the instance pattern before any command or SQL is built, and an
  invalid name is refused with a descriptive error and no plan is executed

#### Scenario: Duplication target name is validated

- **WHEN** a target instance and database name are entered for duplication
- **THEN** both are validated against the instance/PostgreSQL patterns before any command or SQL is built, and
  an invalid target is refused with a descriptive error

### Requirement: Phrase confirmation for sensitive actions

Destructive or data-altering actions SHALL require the operator to type an exact
confirmation phrase that names the operation and target instance. The phrases are English, like the rest of
the canonical interface.

#### Scenario: Correct phrase authorizes execution

- **WHEN** the operator types the exact required phrase (e.g. `DELETE <instance>`, `DELETE-ALL <instance>`,
  `RESTORE <instance>`, `DUPLICATE <instance>`)
- **THEN** the plan proceeds to execution

#### Scenario: Wrong phrase cancels execution

- **WHEN** the operator types anything other than the exact phrase
- **THEN** the operation is cancelled and nothing is executed
