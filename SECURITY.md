# Security Policy

## Scope and threat model

Odoo Instance Manager is an interactive, **root-run** administration tool for Ubuntu servers. It builds and
executes shell command plans that install, reconfigure, back up, and delete Odoo instances, PostgreSQL roles
and databases, Nginx vhosts, TLS material, and Fail2ban jails. Anyone able to run this tool effectively has
full administrative control of the host.

Because of that, the primary safety properties are enforced **in the tool itself**:

- **Preview before apply** — every mutating action renders its full command plan before anything runs.
- **Explicit confirmation** — destructive and data-altering actions require typing an exact confirmation
  phrase naming the operation and instance.
- **Identifier validation** — instance and PostgreSQL identifiers are validated against strict patterns
  before they reach any generated command or SQL.
- **Least surprise on failure** — a failed install triggers a best-effort cleanup of that instance's
  residues.

See [`docs/decisions/0001-plan-preview-apply-safety.md`](docs/decisions/0001-plan-preview-apply-safety.md)
for the rationale.

## Reporting a vulnerability

If you find a security issue — for example a command-injection path through an unvalidated input, a plan that
bypasses confirmation, or a credential handled unsafely — please **do not open a public issue**. Instead,
email the maintainer at the address on the GitHub profile
[@grojof](https://github.com/grojof), or open a private security advisory on the repository.

Include: the affected action/menu path, the input that triggers it, and the observed vs. expected behavior.
A reproduction against a disposable VM is ideal.

## Handling credentials

- Database and admin passwords are entered interactively and passed to `psql`/`pg_dump` via `PGPASSWORD` in
  the generated commands. Treat shell history and process listings on the host as sensitive.
- Do not commit real credentials, dumps, or filestore archives to the repository.
- The recommended permissions baseline in [`docs/safe-controls.md`](docs/safe-controls.md) denies reads of
  common secret files (`.env`, `*.pem`, SSH keys).

## Supported versions

This is an early-stage tool without formal release versioning yet; fixes land on `main`. Run the latest
`main` on any server you manage.
