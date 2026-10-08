# fail2ban-protection Specification

## Purpose

Install and operate Fail2ban to protect the server and individual Odoo
instances: a secure base configuration, per-instance Odoo auth jails, assessment
of whether the Odoo log carries the real client IP, and operational actions
(status, jail detail, unban, regex testing).

## Requirements

### Requirement: Secure base setup

The tool SHALL install Fail2ban when missing and write a base jail configuration enabling `sshd` and
`recidive`, and `nginx-http-auth` and `nginx-botsearch` only when the host has nginx logs (fail2ban refuses the
whole configuration when a jail's log is missing), with `ufw` as the ban action (`banaction_allports` too, so
`recidive` uses it) and operator-tunable timing parameters. The web jails SHALL ban only the web ports, through
ufw's `Nginx Full` application profile. The configuration SHALL be kept only if `fail2ban-client -t` accepts it;
otherwise the previous one is restored. Because the ban action is `ufw`, effective banning SHALL require UFW to
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

- **WHEN** `fail2ban-client -t` refuses the written configuration
- **THEN** the previous files are restored (new ones removed) and the step fails

### Requirement: Per-instance Odoo jail

The tool SHALL enable a dedicated `odoo-auth-<instance>` jail bound to the instance log, installing the shared
Odoo auth filter, keeping both only if `fail2ban-client -t` accepts them, and testing the filter against Odoo's
login-failure line of every supported version (12-18 `Login failed for db:<db> login:<login> from <ip>`, 19
`Login failed for login:<login> from <ip>`, both from the `odoo.addons.base.models.res_users` logger and
followed by the request's perf info) — a test that fails unless each line matches. The jail SHALL ban only the
web ports (ufw's `Nginx Full` profile), so an Odoo login failure never bans SSH.

#### Scenario: Instance jail is created and filter-tested

- **WHEN** the operator activates protection for an instance and supplies its log path
- **THEN** the plan verifies the log exists, writes the `odoo-auth` filter and the `odoo-auth-<instance>` jail
  through a validated staged step, runs `fail2ban-regex` on Odoo's line of 12-18 and of 19 requiring one match
  each, and reloads Fail2ban

### Requirement: Real-client-IP assessment

Before or independent of enabling an Odoo jail, the tool SHALL assess the last lines of an Odoo log to determine
whether public client IPs are present, and warn when only private/gateway IPs are visible. The assessment
inspects the last 300 log lines and matches IPv4 addresses only.

#### Scenario: Private-only log warns and gates activation

- **WHEN** the assessed log shows only private/loopback/link-local IPv4 addresses
- **THEN** the tool warns of the risk of banning the gateway/proxy and requires explicit confirmation before
  enabling the instance jail

#### Scenario: Public IPs present are reported as safe

- **WHEN** the assessed log contains public IPv4 addresses
- **THEN** the tool reports the log carries real client IPs and does not gate activation

#### Scenario: Missing or unreadable log does not gate

- **WHEN** the log is missing, unreadable, or contains no parseable IPv4 address
- **THEN** the tool reports an unknown result and warns, but does not by itself block enabling the jail

### Requirement: Fail2ban operations

The tool SHALL provide operational actions over jails: show status/jails, show a
jail's detail, unban an IP, and test the Odoo regex against a log.

#### Scenario: Unban lists banned IPs then removes the chosen one

- **WHEN** the operator unbans an IP for a jail
- **THEN** the currently banned IPs are listed for selection (or manual entry), and the plan runs `fail2ban-client set <jail> unbanip <ip>`

#### Scenario: Regex test ensures the filter then runs fail2ban-regex

- **WHEN** the operator tests the Odoo regex against a log
- **THEN** the plan ensures the default `odoo-auth` filter exists when targeted, validates the log and filter files, and runs `fail2ban-regex`

#### Scenario: Status tolerates a not-yet-ready socket

- **WHEN** the service is active but the socket has not yet come up
- **THEN** the status view reports a waiting state rather than an error
