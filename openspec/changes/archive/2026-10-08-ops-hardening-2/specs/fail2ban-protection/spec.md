## MODIFIED Requirements

### Requirement: Secure base setup

The tool SHALL install Fail2ban when missing and write a base jail configuration enabling `sshd` and
`recidive`, and `nginx-http-auth` and `nginx-botsearch` only when the host has nginx logs (fail2ban refuses the
whole configuration when a jail's log is missing), with `ufw` as the ban action (`banaction_allports` too, so
`recidive` uses it) and operator-tunable timing parameters, each checked (durations in fail2ban's units, ignore entries as addresses or
networks; the operator's own SSH client address is proposed). The web jails SHALL ban only the web ports, through
the tool's own `ufw-odoo-web` action (`ufw prepend reject … port 80,443 proto tcp`): fail2ban 0.11.2 passes
`ufw[application="Nginx Full"]`'s name unquoted, which ufw refuses, and 1.0+ bans every port when that profile is
missing. `backend` SHALL be set per jail, never in `[DEFAULT]` (which every packaged jail inherits); `sshd` SHALL
read the journal where `/var/log/auth.log` is absent (Debian 12, hosts without rsyslog), installing
`python3-systemd`. The configuration SHALL be kept only if `fail2ban-client -t` accepts it; otherwise — or on a
failed write, or an interruption — the previous one is restored. Because the ban action is `ufw`, effective banning SHALL require UFW to
be installed and active on the host; the tool does not install UFW.

#### Scenario: Base jails are configured and the service is verified ready

- **WHEN** the operator runs the base setup
- **THEN** the plan installs Fail2ban if missing, writes the base config (including operator-supplied ignore IPs
  plus loopback) through a staged step validated with `fail2ban-client -t`, enables the service, reloads it, and
  waits for the Fail2ban socket to respond before succeeding

#### Scenario: UFW is a runtime prerequisite for banning

- **WHEN** the base setup completes on a host without UFW
- **THEN** the jails validate and run, but bans do not take effect until UFW is installed and active (a
  documented prerequisite, not installed by the tool)

#### Scenario: No nginx jail without nginx logs

- **WHEN** the host has no `/var/log/nginx`
- **THEN** the base configuration enables no nginx jail

#### Scenario: A refused configuration is rolled back

- **WHEN** `fail2ban-client -t` refuses the written configuration, a write fails, or the step is interrupted
- **THEN** the previous files are restored (new ones removed) and the step fails

#### Scenario: Web bans work on every supported fail2ban

- **WHEN** a web or Odoo jail bans an address on fail2ban 0.11.2, 1.0.2 or 1.1.0
- **THEN** ufw rejects that address on ports 80 and 443 only

### Requirement: Per-instance Odoo jail

The tool SHALL enable a dedicated `odoo-auth-<instance>` jail bound to the instance log, installing the shared
Odoo auth filter, keeping both only if `fail2ban-client -t` accepts them, and testing the filter against Odoo's
login-failure line of every supported version (12-18 `Login failed for db:<db> login:<login> from <ip>`, 19
`Login failed for login:<login> from <ip>`, both from the `odoo.addons.base.models.res_users` logger and
followed by the request's perf info) — a test that fails unless each line matches. The jail SHALL ban only the
web ports (the `ufw-odoo-web` action), so an Odoo login failure never bans SSH.

#### Scenario: Instance jail is created and filter-tested

- **WHEN** the operator activates protection for an instance and supplies its log path
- **THEN** the plan verifies the log exists, writes the `odoo-auth` filter and the `odoo-auth-<instance>` jail
  through a validated staged step, runs `fail2ban-regex` on Odoo's line of 12-18 and of 19 requiring one match
  each, and reloads Fail2ban

### Requirement: Fail2ban operations

The tool SHALL provide operational actions over jails: show status/jails, show a
jail's detail, unban an IP, and test the Odoo regex against a log.

#### Scenario: Unban lists banned IPs then removes the chosen one

- **WHEN** the operator unbans an IP for a jail
- **THEN** the currently banned IPs are listed for selection (or manual entry), and the plan runs `fail2ban-client set <jail> unbanip <ip>`

#### Scenario: Regex test ensures the filter then runs fail2ban-regex

- **WHEN** the operator tests the Odoo regex against a log
- **THEN** the plan validates the log and runs `fail2ban-regex` with the filter on disk or, when the default
  `odoo-auth` filter is not installed, with the tool's filter from a temporary file — a test writes nothing

#### Scenario: Status tolerates a not-yet-ready socket

- **WHEN** the service is active but the socket has not yet come up
- **THEN** the status view reports a waiting state rather than an error
