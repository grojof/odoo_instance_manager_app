# Align specs and docs with actual behavior

## Why

The coherence audit found the specs and docs overclaiming or omitting real behavior: safety guarantees stated
more strongly than the code delivers, and several real behaviors (the config update replaying the full base
setup, the audit's optional report export, the UFW dependency, the `list_db` default) undocumented. Honest
docs are the foundation for the upcoming refactor.

## What changes

Documentation and specs only, plus two trivial code corrections that make the tool honor its own claims:

- **execution-safety** — cleanup drops the DB role by **install mode**, not "when the run created it".
- **instance-provisioning** — no-autostart path explicitly disables then starts the service.
- **instance-configuration** — the config update **replays the full base setup** (apt/clone/venv/pip); status
  TLS classification includes the sixth "incomplete" state.
- **data-backup-restore** — the target-DB existence check is local-only; duplication copies DB+filestore and
  does not provision the target instance.
- **server-audit** — read-only is qualified: an optional operator-initiated report file and active TLS checks
  are the only writes/active probes; the overview also reports PostgreSQL/Nginx service state and `nginx -t`;
  discovery recognizes the legacy conf path.
- **fail2ban-protection** — `banaction = ufw` requires UFW installed/active (documented prerequisite, not
  installed by the tool); real-IP assessment samples the last 300 lines, IPv4 only, and "unknown" does not gate.
- **Docs** — matching updates to README, installation, configuration-reference (incl. the `list_db = True` /
  guessable `admin_passwd` security note), instance-management, security-fail2ban, server-audit, architecture;
  Python 3.12+ stated as the floor.
- **Code (trivial):** the misleading prompt "IP servidor app para pg_hba/UFW" → "…para regla pg_hba" (no UFW
  rule is ever added), and `libtiff5-dev` → `libtiff-dev` (the former does not exist on Ubuntu 24.04, which the
  tool targets, so the very first install step would fail).

## Impact

- Specs updated: execution-safety, instance-provisioning, instance-configuration, data-backup-restore,
  server-audit, fail2ban-protection.
- Docs updated: README + 6 pages.
- Code: two one-line corrections in `workflows.py` and `planners.py`; no behavioral logic change beyond the
  corrected package name.
