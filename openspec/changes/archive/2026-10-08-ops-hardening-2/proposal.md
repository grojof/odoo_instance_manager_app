# Operations hardening, second pass

## Why

The second audit ran the operations against real fail2ban (0.11.2, 1.0.2, 1.1.0), nginx and logrotate:

- **fail2ban 0.11.2** (Ubuntu 22.04, Debian 11) passes `ufw[application="Nginx Full"]`'s name unquoted. ufw
  refuses it, so no web or Odoo ban ever applied. A negative control reproduces this.
- **Debian 12** has no `auth.log`. Our `[DEFAULT] backend = auto` made `sshd` look for that file, so
  `fail2ban-client -t` failed and the base setup was rolled back.
- **Staged writes** wrote, chmodded and moved without checking each step. A failed write, a failed `mktemp` or
  an interruption could leave half a configuration.
- **Certificates.**
  - "Let's Encrypt" and "leave untouched" pointed the vhost at the tool's own files, which may not exist.
  - A certbot-managed vhost was swapped back to self-signed.
  - A cancelled file pick still built the plan.
- **Update configuration** wrote `odoo.conf` before checking the new values and before setting the role's
  password. With a new password for a remote role, it restarted at once, before that role had it.
- **UFW.** Enable and Delete skipped the SSH guard, and the PostgreSQL source took any value.
- **logrotate and fail2ban inputs.** The logrotate policy was written before validation, with a free-text size.
  fail2ban's durations and ignore list were not checked.
- **"Test the Odoo regex"** rewrote the filter.

## What changes

- **fail2ban.**
  - A `ufw-odoo-web` action bans on 80/443 on every version.
  - `backend` is set per jail; `sshd` uses the journal (with `python3-systemd`) where `auth.log` is absent.
  - Validated durations and networks; the admin's SSH address is proposed for the ignore list.
  - The regex test is read-only.
- **Staged writes.** Back up all files first, then check each write, with an INT/TERM trap. Nothing is touched
  without a backup directory.
- **Certificates.** "Let's Encrypt" names `/etc/letsencrypt/live/<domain>/`, and "untouched" names the files the
  current vhost names. Missing files or a cancelled pick write no HTTPS vhost.
- **Update.** Order: role password, login check with the new values, write, restart. No restart for a remote
  new password, and the backup path is shown even on failure.
- **UFW.** Enabling allows SSH first, deleting an SSH rule asks first, and the PostgreSQL source is one address.
- **logrotate.** Staged, validated with `logrotate -d`, and the size is validated.

## Impact

- Specs: `fail2ban-protection`, `firewall-ufw`, `web-proxy-tls`, `log-rotation`, `instance-configuration`.
- Code: `planners.py`, `models.py`, `workflows/{fail2ban,firewall,install,manage,logrotate,backup_restore}.py`.
- Tests: `tests/test_ops_hardening.py`.
- Verification: `tools/verify_ops_configs.py` (CI) now covers:
  - fail2ban 1.1.0, 1.0.2 and 0.11.2, each banning a stub ufw rendered by fail2ban itself, plus the 0.11.2
    negative control;
  - staged-write failures;
  - logrotate rollback;
  - Let's Encrypt and unknown-version vhosts under `nginx -t`.
