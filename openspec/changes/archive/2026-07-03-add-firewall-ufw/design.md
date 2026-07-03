# Design

## Lock-out safety

The one real risk of a firewall tool is locking the operator out over SSH. The baseline therefore **allows the
SSH port before enabling UFW**, and the workflow warns to double-check the SSH port first. `ufw --force enable`
is always the last command. The plan preview shows exactly what will run before anything is applied.

## Planners (pure)

- `plan_ufw_base_setup(ssh_port, allow_http, allow_https, pg_from_ip)` — install-if-missing, default policies,
  SSH allow, optional HTTP/HTTPS, optional `ufw allow from <ip> to any port 5432 proto tcp`, then enable.
  Ports are coerced to `int`; the IP is shell-quoted.
- `plan_ufw_allow_port(port, proto)` — `ufw allow <port>/<tcp|udp>` (proto defaults to tcp for anything but
  udp).
- `plan_ufw_delete_rule(number)` — `ufw --force delete <n>`.

## Workflow

`manage_firewall` shows `ufw status verbose` on each loop and offers the operations. Status and the numbered-
rule listing are read-only `run(...)`; the mutating operations go through `_execute_plan`.

## Testing

Pure planners are unit-tested: baseline rule set + ordering (SSH before enable, enable last), optional rules
omitted when declined, and proto coercion. Interactive status/enable/disable are operator-accepted.

## Out of scope

Advanced UFW (application profiles, rate limiting, IPv6 specifics) — the baseline covers the common Odoo server
case; anything else can be added with "Permitir puerto" or `ufw` directly.
