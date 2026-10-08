# Keep secrets out of sight

## Why

Every database password the tool used was written into the command text (`PGPASSWORD=… psql …`), and the
role password into `psql -c "CREATE ROLE … PASSWORD '…'"`. A plan step runs as `bash -lc "<command>"`, so the
password sat in that process's arguments, which any local user — another instance's Odoo user included — reads
with `ps` for as long as the step runs (a long `pg_dump` or `pg_restore`). The same text was printed in the plan
preview (with `odoo.conf`'s `admin_passwd` and `db_password` in its heredoc) and again in the error of a failed
step. A remote server that dropped packets also held a probe, and the menu, until TCP gave up.

## What changes

- A plan step carries its secrets in `Command.env` (the step's environment, readable only by root) and what the
  preview shows in `Command.display` (secrets masked). Every libpq client takes `PGPASSWORD` from the
  environment, with `PGCONNECT_TIMEOUT=10`; SQL holding a password is fed to psql on stdin.
- Files are written atomically (private temporary file, chmod, rename) with their content in the environment;
  the preview shows the content with secrets masked.
- A failed step's error names the step, not its command.
- Smaller fixes: the addon dependency check asks by distribution name first, as Odoo does (`python-stdnum`
  was reported missing); the health check reaches a Unix-socket database (`db_host = False`); a failed export
  no longer crashes the CLI; the server report's database list no longer matches by name prefix.

## Impact

- Specs: `execution-safety`, `addon-inventory`.
- Code: `system.py`, `planners.py`, `workflows/{addons,backup_restore,common,health,manage,purge,report}.py`.
- Tests updated; `tools/verify_secrets.py` runs the steps and looks at `ps`.
