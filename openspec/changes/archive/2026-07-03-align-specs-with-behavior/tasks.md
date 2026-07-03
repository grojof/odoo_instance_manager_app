# Tasks

## 1. Spec deltas

- [x] 1.1 execution-safety: cleanup drops DB role by install mode (not "when created").
- [x] 1.2 instance-provisioning: autostart-off disables then starts.
- [x] 1.3 instance-configuration: status TLS "incomplete" state; update replays full base setup.
- [x] 1.4 data-backup-restore: restore existence check is local-only; duplication does not provision target.
- [x] 1.5 server-audit: read-only qualified (optional export + active TLS checks); overview PG/Nginx + nginx -t;
  legacy conf path in discovery.
- [x] 1.6 fail2ban-protection: UFW runtime prerequisite; real-IP 300-line/IPv4/unknown behavior.

## 2. Docs

- [x] 2.1 README + installation + configuration-reference: Python 3.12+; drop firewall/UFW wording; add
  `list_db = True` security note.
- [x] 2.2 instance-management: update replays base setup + class-defaults hazard; duplication scope; local
  existence check; TLS "incomplete".
- [x] 2.3 security-fail2ban: UFW prerequisite; real-IP 300-line/IPv4/unknown.
- [x] 2.4 server-audit: optional export + active checks; PG/Nginx rows; legacy conf path.
- [x] 2.5 architecture: soften the "via system.py only" side-effects claim.

## 3. Code corrections

- [x] 3.1 Reword the app-server-IP prompt to drop the non-existent UFW reference.
- [x] 3.2 `libtiff5-dev` → `libtiff-dev` (honor the Ubuntu 24.04 target).

## 4. Verify

- [x] 4.1 `openspec validate --specs`, `docs-check`, `ruff`, `pytest`, compile all pass.
