## ADDED Requirements

### Requirement: Instance health check

The tool SHALL provide a read-only health check for an instance that reports the systemd service state, local
HTTP responsiveness, database connectivity, and free disk space, without changing anything.

#### Scenario: Health check reports each probe

- **WHEN** the operator runs the health check for an instance
- **THEN** the tool shows, each tagged healthy or not: whether the systemd service is active (and its
  autostart state), whether the instance answers on its local HTTP port, whether its database is reachable
  with the config credentials, and the free space on the instance home and data directory — running only
  inspection commands and an HTTP GET, with no mutating command

#### Scenario: Low disk space is flagged

- **WHEN** a checked filesystem is at or above 90% usage
- **THEN** that disk row is marked as a problem rather than healthy

#### Scenario: Active-but-unresponsive service is surfaced

- **WHEN** the service is active but the local HTTP port does not answer
- **THEN** the check warns that the service is up but not responding
