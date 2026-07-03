# fail2ban-protection Specification

## Purpose

Install and operate Fail2ban to protect the server and individual Odoo
instances: a secure base configuration, per-instance Odoo auth jails, assessment
of whether the Odoo log carries the real client IP, and operational actions
(status, jail detail, unban, regex testing).

## Requirements

### Requirement: Secure base setup

The tool SHALL install Fail2ban and write a base jail configuration enabling
`sshd`, `nginx-http-auth`, `nginx-botsearch`, and `recidive`, with `ufw` as the
ban action and operator-tunable timing parameters.

#### Scenario: Base jails are configured and the service is verified ready

- **WHEN** the operator runs the base setup
- **THEN** the plan installs Fail2ban, writes the base config (including operator-supplied ignore IPs plus loopback), validates with `fail2ban-client -t`, enables and restarts the service, and waits for the Fail2ban socket to respond before succeeding

### Requirement: Per-instance Odoo jail

The tool SHALL enable a dedicated `odoo-auth-<instance>` jail bound to the
instance log, installing the shared Odoo auth filter and testing the filter
against the log before activation.

#### Scenario: Instance jail is created and filter-tested

- **WHEN** the operator activates protection for an instance and supplies its log path
- **THEN** the plan installs the `odoo-auth` filter, writes the `odoo-auth-<instance>` jail for that log, verifies the log exists, runs `fail2ban-regex` against it, validates the config, and (re)starts Fail2ban

### Requirement: Real-client-IP assessment

Before or independent of enabling an Odoo jail, the tool SHALL assess the last
lines of an Odoo log to determine whether public client IPs are present, and
warn when only private/gateway IPs are visible.

#### Scenario: Private-only log warns and gates activation

- **WHEN** the assessed log shows only private/loopback/link-local IPs
- **THEN** the tool warns of the risk of banning the gateway/proxy and requires explicit confirmation before enabling the instance jail

#### Scenario: Public IPs present are reported as safe

- **WHEN** the assessed log contains public IPs
- **THEN** the tool reports the log carries real client IPs and does not gate activation

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
