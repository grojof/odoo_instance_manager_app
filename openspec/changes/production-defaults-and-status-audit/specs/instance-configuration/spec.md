## MODIFIED Requirements

### Requirement: Instance status inspection

The tool SHALL expose the instance's status as separate, on-demand views reachable from the management
menu — expected locations/names, detected resource state, and useful configuration values — rather
than rendering the full status on every menu display. Each view SHALL be individually selectable so
the operator sees only the requested section, and the detected-state view SHALL cover the Linux user,
home, config file, systemd service (existence and active state), DB role, data dir, TLS certificate
mode, and optional database existence.

#### Scenario: Status is split into selectable views

- **WHEN** the operator opens the management menu for an instance
- **THEN** locations/names, detected resource state, and useful config values are each reachable as a
  separate menu action instead of being printed together

#### Scenario: The management menu does not auto-render the full status

- **WHEN** the management menu is (re)displayed after an action
- **THEN** the full status tables are not re-printed automatically; only the menu (optionally with a
  compact one-line summary) is shown

#### Scenario: Detected-state view marks each resource

- **WHEN** the operator opens the detected-state view
- **THEN** each checked resource (Linux user, home, config, service existence/active, DB role, data
  dir, TLS mode, and optional database) is marked present or missing, and the TLS certificate mode is
  classified (self-signed / custom-CA / external / Let's Encrypt / incomplete / not configured)

## ADDED Requirements

### Requirement: Security and production posture audit

The management status SHALL provide an on-demand security-and-production posture view that inspects the
instance config and host read-only and reports, each with an OK/WARN/INFO classification and a short
rationale: whether the database manager is exposed (`list_db = True`); whether the master password
(`admin_passwd`) or the DB password is still the guessable instance-name default; whether
`wkhtmltopdf` is installed and its version; whether the worker count is sized for the detected CPU/RAM;
whether `db_sslmode` is set when the DB host is remote; and whether a `dbfilter` is configured.

#### Scenario: Posture view flags an exposed database manager

- **WHEN** the instance config has `list_db = True`
- **THEN** the posture view marks the database-manager exposure as WARN with a rationale recommending
  `list_db = False` (plus `dbfilter`) for production

#### Scenario: Posture view flags guessable default credentials

- **WHEN** the master password or DB password equals the instance name in plaintext
- **THEN** the posture view marks it WARN as a guessable default

#### Scenario: Hashed master password is treated as acceptable

- **WHEN** the master password value in the config is stored hashed (not plaintext)
- **THEN** the posture view does not flag it as a guessable default

#### Scenario: Posture view reports wkhtmltopdf presence and version

- **WHEN** the posture view runs
- **THEN** it reports whether `wkhtmltopdf` is installed and its version, marking a missing or
  un-patched/too-old build as WARN

#### Scenario: Posture view flags an unencrypted remote DB connection

- **WHEN** the DB host is remote and `db_sslmode` is unset or permits cleartext fallback
  (`disable`/`allow`/`prefer`)
- **THEN** the posture view marks the DB connection as WARN and recommends `require` or stricter
