# Tasks

- [x] 1. data-backup-restore delta; `openspec validate --specs` (1.4.1) passes.
- [x] 2. Catalogue: delete rules, optional labels, Spanish EDI per version, VERI*FACTU and TicketBAI (Odoo, OCA),
      EDI proxy (17-19, 14-16 parameter, MY/GR), web push, cloud storage, certificates, SMS, calendars per table,
      IAP long tokens, mail host and `login` sink, `cli` and EDI checks, citations.
- [x] 3. Odoo's own neutralize.sql step (16.0-19.0), read as the instance user, run as the owner.
- [x] 4. Staged copy: one step, dropped on failure, staging comment, CONNECT at hand-over, leftovers replaced.
- [x] 5. Restore: local as a duplication, remote atomic with the service restarted; `--no-comments`.
- [x] 6. Order: target files before the database; replica database after the instance.
- [x] 7. Tests and verification (unit, `verify_privilege`, `verify_neutralisation` on Odoo 14 and 18).
