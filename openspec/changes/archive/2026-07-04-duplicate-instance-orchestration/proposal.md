# Orchestrated instance duplication (replica or refresh)

## Why

*Duplicate instance* today only copies the database (and optionally the filestore) — it does **not** create the
target's system user, virtualenv, `odoo.conf`, systemd service, or Nginx vhost, so the duplicated "instance"
does not actually run. The real use case is: duplicate a **production** instance into a **development** one,
and, if the dev instance already exists, **refresh** it from production to keep an up-to-date dev environment.

## What changes

- **data-backup-restore — Duplication (MODIFIED):** duplication becomes end-to-end and existence-aware:
  - **Target does not exist → replica:** provision the target instance fully — reusing the base setup (system
    user, home, Odoo checkout at the **source's version**, virtualenv, `odoo.conf`, systemd unit) and,
    optionally, Nginx — with its **own domain, non-colliding ports, and freshly generated secrets**, then seed
    it with the source database and filestore. The service is provisioned **without starting**, seeded, then
    started.
  - **Target exists → refresh in place:** stop the target service, replace its database and filestore from the
    source, apply the migration semantics, and restart — **without** recreating its config or service.
  - **Copy method is selectable:** a fast PostgreSQL **template** copy (same-owner), or a robust
    **`pg_dump | pg_restore --no-owner`** that reassigns ownership for a cross-user target (recommended for
    production→development). Copied/moved + neutralize semantics apply in both cases; phrase confirmation
    remains.

- Enabling change: `plan_odoo_base_setup` gains a `start_now` flag so the target can be provisioned before its
  database exists and started afterward.

## Impact

- Spec: `data-backup-restore`.
- Code: `planners.py` (`start_now`), `backup_restore.py` (DB seed helpers for both methods + drop-for-refresh;
  the orchestrated `_duplicate_instance`), reusing install helpers (`_suggest_instance_ports`, secret
  generation) and `plan_odoo_base_setup`/`plan_nginx_*`.
- Docs: `docs/operations/instance-management.md`; `CHANGELOG.md` `[Unreleased]`.
- Tests: `tests/test_backup_restore.py` (seed-command methods, drop-for-refresh) and `tests/test_planners.py`
  (`start_now`).

## Out of scope

- The standalone "Duplicate database" backup action and the manage-menu submenus are separate follow-up changes.
