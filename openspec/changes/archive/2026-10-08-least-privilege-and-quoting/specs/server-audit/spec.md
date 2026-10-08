## MODIFIED Requirements

### Requirement: Read-only guarantee

The audit SHALL be read-only with respect to server configuration: it runs discovery and inspection commands
and never builds or applies a plan that installs, configures, or deletes anything. It MAY, at the operator's
request, write a single report file and run active (read-only) TLS certificate checks.

#### Scenario: Report never mutates server configuration

- **WHEN** the full report runs
- **THEN** only inspection/discovery commands execute and no install, configuration, or deletion command is
  produced or applied

#### Scenario: Optional report export is operator-initiated

- **WHEN** the operator opts to export the report
- **THEN** the tool writes a single report file to the chosen path (default under `./reports/`), which is the
  only file the audit creates; the file must be new (an existing file or a link there is refused) and is
  private (`600`)

#### Scenario: Instance binaries are read, not run

- **WHEN** the report shows an instance's Python version
- **THEN** it reads the venv's `pyvenv.cfg` instead of running the instance-owned interpreter as root

#### Scenario: Optional active TLS checks are read-only

- **WHEN** the operator opts into active TLS checks with an expiry threshold
- **THEN** the tool runs read-only `openssl` certificate checks and does not modify any certificate or service
