# Neutralise copies completely, before any Odoo can see them

## Why

The neutralisation of a restored or duplicated database turned off crons, mail servers and fetchmail, each with
`|| true`. With no mail server active, Odoo falls back to `smtp_server` in `odoo.conf` (`localhost:25` by
default), so a local MTA still relayed real mail; payment providers, carriers, OAuth, calendar tokens, webhooks,
IAP, EDI/SII and the base URL stayed live. And the copy was owned by the instance's role from the start: Odoo's
cron worker lists every database its role owns (`list_dbs`, which ignores `dbfilter`), so it ran production's
overdue crons on the copy before the neutralisation — or forever, when an earlier step failed.

## What changes

- `instance_manager/neutralise.py`: the catalogue the sibling project odoo_dwg keeps (Odoo's own
  `neutralize.sql` 16.0-19.0, made to work on 12.0-19.0 and on the OCA modules a Spanish or queue-based instance
  runs), one-way like Odoo's, every rule guarded by its table and columns. A mail sink (`invalid:1025`) keeps
  Odoo from falling back to the configuration file's server; production's SMTP credentials are dropped.
- Applied as one statement that stops the plan when it fails, then a guard that fails the plan when anything can
  still act on the outside.
- Copied mode gives the copy new `database.uuid`, `database.secret` and `database.create_date`, as Odoo's copy does.
- A seeded copy is owned by `postgres` until it is neutralised, then handed to its role; a restore stops the
  instance's service until the copy is neutralised.
- A read-only *Check a copy is neutralised* action in *Status & health*.

## Impact

- Specs: `data-backup-restore`.
- Code: `neutralise.py` (new), `workflows/backup_restore.py`, `workflows/manage.py`, `i18n.py`.
- Tests: `tests/test_neutralise.py`; `tools/verify_neutralisation.py` runs it on real Odoo 14 and 18 databases.
