# Guard the paths that remove or overwrite

## Why

A second audit, run by executing the plans, found paths where the preview and the confirmation phrase show a
plan that is itself wrong:

- **Install** never checked that the instance name was free. Installing over an existing instance, or pressing
  Ctrl+C at the confirmation prompt, ran a cleanup that removed that instance's home, config, unit and vhosts.
  System names were accepted: an instance named `backup` reuses the account whose home is `/var/backups`.
- **Purge** dropped every database that had a folder in the filestore root, with no owner check. On a data dir
  shared by several instances (`/var/lib/odoo`), it removed the other instances' filestores and dropped their
  databases. A role named after the instance was dropped even when another instance used it, and `postgres` was
  accepted as the instance role.
- **Every install** ran `chown -R <instance> /var/log/odoo`: the newest instance owned every other instance's
  log, those instances logged to stdout, their fail2ban jails saw nothing, and logrotate's `su` failed.
- **Delete** ran a bare `nginx -t` before dropping the database (no nginx means no drop), read the data dir
  only from the current `odoo.conf` location, and dropped a database without checking its owner.
- **Copies** chowned the whole resolved data dir (another instance's files when shared), `cp -a` nested the copy
  inside an existing target, a refresh removed the target filestore with `rm -rf`, and its phrase named the
  source. A replica's filestore went to `~/.local/share/Odoo` while its `odoo.conf` named `/var/lib/odoo/<t>`.
- **Backups** accepted `/tmp` or `/` as their directory, then made it `700`; retention kept the newest by mtime,
  so a copied old backup outlived newer ones.

## What changes

- A new instance needs a free name: no system account or service name, and nothing on the host under it.
- Install confirms outside the failure handling; a failure while applying previews the cleanup of what that run
  made and asks before applying it. The data dir and the role are removed only when the run created them.
- Purge selects databases by owner or exact name only, refuses administrator roles, drops databases before their
  filestores, removes a shared data dir's filestores one by one, keeps a role another instance uses, removes the
  Linux user only when the tool made it, and removes the logrotate policy.
- `/var/log/odoo` is root's (755); each instance owns only its log, earlier instances get theirs back, and the
  logrotate policies lose `su`.
- Delete checks the database's owner, drops it before the config goes, resolves the data dir from both config
  locations, reloads nginx only if installed, and removes the logrotate policy.
- Copies chown only what is the target's, move an existing target filestore aside, copy into it, and check the
  source first; a refresh asks for `REPLACE <target>`; the data dir of the config being built wins.
- Backup directories must be dedicated; retention keeps the newest names, and file names yield only valid
  database names.

## Impact

- Specs: `execution-safety`, `instance-provisioning`, `instance-removal`, `data-backup-restore`, `disk-usage`,
  `scheduled-backups`, `log-rotation`.
- Code: `models.py`, `planners.py`, `system.py`, `workflows/{common,install,purge,manage,backup_restore,
  diskusage,scheduled_backup}.py`, `i18n.py`.
- Tests: `tests/test_destructive_guards.py`; `tools/verify_data_safety.py` runs the new steps against stubs and
  a PostgreSQL of its own.
