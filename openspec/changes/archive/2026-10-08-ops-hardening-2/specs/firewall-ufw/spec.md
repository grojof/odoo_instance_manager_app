## MODIFIED Requirements

### Requirement: UFW secure baseline

The tool SHALL install UFW when missing and apply a secure baseline — default deny incoming, allow outgoing,
allow SSH before enabling (to avoid lock-out), and allow HTTP/HTTPS — optionally allowing PostgreSQL from a
single app-server IP (one address, never a network or `any`), then enable UFW. The SSH port SHALL default to the one SSH listens on (`sshd -T`, and
`ssh.socket` on socket-activated hosts), and a port SSH does not listen on SHALL require an explicit
confirmation.

#### Scenario: Baseline is applied in a lock-out-safe order

- **WHEN** the operator applies the UFW baseline with an SSH port
- **THEN** the plan installs UFW if missing, sets default deny-incoming / allow-outgoing, allows the SSH port,
  allows HTTP (80) and HTTPS (443) when chosen, allows PostgreSQL (5432) from the given IP when provided, and
  enables UFW last — with the SSH allow ordered before the enable

#### Scenario: Optional rules are omitted when declined

- **WHEN** HTTP, HTTPS, or the PostgreSQL allow are declined
- **THEN** the corresponding rules are not added

#### Scenario: The detected SSH port is the default

- **WHEN** SSH listens on port 2222
- **THEN** the baseline proposes 2222, and allowing 22 instead requires confirming that new SSH sessions would
  be locked out

### Requirement: UFW operations

The tool SHALL provide read-only status and operations to allow a port, delete a rule by number, and enable or
disable UFW, each mutating action through the preview/confirm/apply flow. A delete SHALL run only if the rule at
that number is still the line the operator was shown (fail2ban prepends its bans, shifting the numbers).
Enabling UFW SHALL allow the ports SSH listens on first, asking for confirmation when none is detected, and
deleting a rule that lets SSH in SHALL require confirmation.

#### Scenario: Enabling never shuts SSH out

- **WHEN** the operator enables UFW
- **THEN** the plan allows the detected SSH ports before enabling it

#### Scenario: Deleting the SSH rule is confirmed

- **WHEN** the numbered rule allows SSH (its port, or the `OpenSSH` profile)
- **THEN** the tool warns that it can lock the operator out and deletes it only on confirmation

#### Scenario: Status is read-only

- **WHEN** the operator views UFW status
- **THEN** the tool shows `ufw status verbose` without changing anything

#### Scenario: A rule can be allowed and deleted

- **WHEN** the operator allows a port or deletes a numbered rule
- **THEN** the plan runs the matching `ufw allow <port>/<proto>`, or checks that the numbered line is unchanged
  and then runs `ufw --force delete <n>`, after preview and confirmation

#### Scenario: A shifted list deletes nothing

- **WHEN** the rule list changed between the listing and the delete
- **THEN** the step fails without deleting any rule
