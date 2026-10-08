# Harden the server operations: fail2ban, UFW, nginx, packaging

## Why

- The published v1.2.0 wheel did not run: `packages = ["instance_manager"]` left out `instance_manager.workflows`,
  and CI and release only ever used an editable install.
- fail2ban: one missing log (nginx jails on a host without nginx, or a purged instance's jail) makes fail2ban
  refuse the whole configuration at its next start, the sshd jail included; the jails were written before they
  were validated and never rolled back. The Odoo filter missed Odoo 19's line (`Login failed for login:…`), and
  its plan test passed with zero matches. A ban for an Odoo login failure banned every port, SSH included.
- UFW: rules were deleted by number, and fail2ban prepends its bans, so the number the operator read could point
  at the SSH allow by the time it ran; the SSH port was never detected.
- nginx: the vhost was enabled before `nginx -t`, so a failed change stayed enabled and took every instance down
  at the next nginx restart; the HTTP vhost limited uploads to 1 MB; the HTTPS vhost lacked what Odoo's
  deployment guide sets (HSTS, the Secure session cookie, its TLS settings, gzip).

## What changes

- **Packaging:** `packages.find`; CI and release build the wheel and import it from a clean venv; the release
  fails when the changelog has no section for the tag.
- **fail2ban:** jails and filter written through a staged step kept only if `fail2ban-client -t` accepts them
  (restored otherwise); nginx jails only when nginx logs exist; a filter anchored on Odoo's logger matching
  12-18 and 19, tested against both lines (must match); web and Odoo bans scoped to ufw's `Nginx Full`
  profile; recidive uses ufw.
- **UFW:** the delete runs only if the numbered line is still the one shown; the SSH port is detected from
  `sshd -T` and `ssh.socket`, and a port SSH does not listen on is confirmed.
- **nginx:** enable + `nginx -t` + rollback in one step; HTTP vhost `client_max_body_size`; HTTPS vhost with
  the guide's TLS settings, HSTS and `proxy_cookie_flags` (nginx ≥ 1.19.8), and gzip.

## Impact

- Specs: `fail2ban-protection`, `firewall-ufw`, `web-proxy-tls`.
- Code: `planners.py`, `system.py`, `workflows/{fail2ban,firewall}.py`, `pyproject.toml`, CI/release workflows.
- Tests: `tests/test_ops_configs.py`; `tools/verify_ops_configs.py` runs the real nginx and fail2ban.
