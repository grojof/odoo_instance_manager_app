## MODIFIED Requirements

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
