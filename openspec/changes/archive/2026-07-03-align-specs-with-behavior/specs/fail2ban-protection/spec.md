## MODIFIED Requirements

### Requirement: Secure base setup

The tool SHALL install Fail2ban and write a base jail configuration enabling `sshd`, `nginx-http-auth`,
`nginx-botsearch`, and `recidive`, with `ufw` as the ban action and operator-tunable timing parameters. Because
the ban action is `ufw`, effective banning SHALL require UFW to be installed and active on the host; the tool
does not install UFW.

#### Scenario: Base jails are configured and the service is verified ready

- **WHEN** the operator runs the base setup
- **THEN** the plan installs Fail2ban, writes the base config (including operator-supplied ignore IPs plus
  loopback), validates with `fail2ban-client -t`, enables and restarts the service, and waits for the Fail2ban
  socket to respond before succeeding

#### Scenario: UFW is a runtime prerequisite for banning

- **WHEN** the base setup completes on a host without UFW
- **THEN** the jails validate and run, but bans do not take effect until UFW is installed and active (a
  documented prerequisite, not installed by the tool)

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
