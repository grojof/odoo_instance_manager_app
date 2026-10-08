# Copies done whole, neutralised as Odoo does

## Why

The second audit ran restores and duplications into failures, and read the neutralisation catalogue against
the Odoo 14.0-19.0 and OCA l10n-spain sources.

- **A failed restore** left an armed copy. The plan stopped the service, created the database owned by the
  instance's role (so visible to its cron worker), and stopped at the first error, such as a dump whose extension
  comment the role may not set. The service stayed stopped, and a retry was refused because the target existed.
- **A failed duplication** left a postgres-owned database that blocked every retry ("belongs to role
  postgres").
- **The copy's role got `CONNECT` when it was seeded.** An Odoo with `db_name` set connects by name, without
  listing, so it could reach the copy before it was neutralised.
- **Rules that named columns some versions lack were skipped silently**, leaving those copies in production:
  - SII and TicketBAI on 14.0-17.0 use `l10n_es_edi_test_env`;
  - the EDI proxy on 14.0-16.0 reads a parameter;
  - Google Calendar tokens on 15.0-17.0 live in `google_calendar_credentials`;
  - IAP's label column is not stored on 18.0-19.0.
- **Uncovered:**
  - VERI*FACTU (Odoo and OCA), OCA TicketBAI, web push keys and devices, cloud storage, certificate and SMS
    passwords, and the Malaysian and Greek EDI;
  - a mail sink cloned from a `cli` server, which sends through `odoo.conf`;
  - archived mail servers that 12.0-15.0 still use when a message names them.
- **Wrong citations:** the versions given for fetchmail, mail credentials, Microsoft settings and the Google
  rules.

## What changes

- **One step per copy.** The seed, identity, neutralisation, check and hand-over form one staged step on the
  local server. A failure drops only the database that step created; the target filestore is copied before it.
- **Hand-over:** the copy is marked with a staging comment until it is handed over, and the hand-over grants
  `CONNECT` and takes `CREATE` on `public` from `PUBLIC`. A marked leftover is replaced, never refused.
- **Restore.**
  - A local restore goes the same way, restored as the instance's role, with no service stop.
  - A remote restore creates, restores and neutralises in one step. If any part fails, it drops the database and
    restarts the service.
  - Both use `--no-comments`, and the service starts after the files are restored.
- **Odoo's own `neutralize.sql`** of every installed module runs first on 16.0-19.0. It is read from the
  instance's checkout as its user, and runs as the copy's owner.
- **The catalogue** gains `DELETE` rules, optional labels, and rules per version for everything listed above. The
  mail sink logs in with `login`, the check rejects `cli` servers, and the citations are corrected.

## Impact

- Specs: `data-backup-restore`.
- Code: `neutralise.py`, `system.py`, `workflows/{backup_restore,common}.py`.
- Tests: `tests/test_copies_neutralise.py`.
- Verification:
  - `tools/verify_privilege.py` (CI) runs the staged copy: success, failure, an existing target, and a leftover;
  - `tools/verify_neutralisation.py` (real Odoo) checks Odoo's own SQL, the EDI demo parameter and the web push
    key.
