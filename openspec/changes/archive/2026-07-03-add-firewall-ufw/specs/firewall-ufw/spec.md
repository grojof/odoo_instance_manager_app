## ADDED Requirements

### Requirement: UFW secure baseline

The tool SHALL install UFW when missing and apply a secure baseline — default deny incoming, allow outgoing,
allow SSH before enabling (to avoid lock-out), and allow HTTP/HTTPS — optionally allowing PostgreSQL from a
single app-server IP, then enable UFW.

#### Scenario: Baseline is applied in a lock-out-safe order

- **WHEN** the operator applies the UFW baseline with an SSH port
- **THEN** the plan installs UFW if missing, sets default deny-incoming / allow-outgoing, allows the SSH port,
  allows HTTP (80) and HTTPS (443) when chosen, allows PostgreSQL (5432) from the given IP when provided, and
  enables UFW last — with the SSH allow ordered before the enable

#### Scenario: Optional rules are omitted when declined

- **WHEN** HTTP, HTTPS, or the PostgreSQL allow are declined
- **THEN** the corresponding rules are not added

### Requirement: UFW operations

The tool SHALL provide read-only status and operations to allow a port, delete a rule by number, and enable or
disable UFW, each mutating action through the preview/confirm/apply flow.

#### Scenario: Status is read-only

- **WHEN** the operator views UFW status
- **THEN** the tool shows `ufw status verbose` without changing anything

#### Scenario: A rule can be allowed and deleted

- **WHEN** the operator allows a port or deletes a numbered rule
- **THEN** the plan runs the matching `ufw allow <port>/<proto>` or `ufw --force delete <n>` after preview and
  confirmation
