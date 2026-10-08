# Tasks

- [x] 1. Spec deltas; openspec 1.4.1 validates.
- [x] 2. fail2ban: ufw-odoo-web action, per-jail backend, journal for sshd, validated inputs, read-only regex test.
- [x] 3. Staged writes and the nginx switch: backups first, checked writes, INT/TERM trap.
- [x] 4. Certificate modes: Let's Encrypt and untouched name existing files; cancel and missing files stop.
- [x] 5. Update order; remote password without restart; backup path on failure.
- [x] 6. UFW SSH guard on enable and delete; one PostgreSQL source address.
- [x] 7. logrotate staged with logrotate -d; maxsize validated.
- [x] 8. Tests; verify_ops_configs across fail2ban 0.11.2, 1.0.2 and 1.1.0 (CI gets 3.9 and 3.11).
