# Least privilege and quoting for what reaches root

## Why

The second audit ran the generated steps with hostile inputs:

- **Certificates:** the operator's file paths went into the root shell in single quotes, so a file named
  `x'$(…)'.crt` ran its name. The files also replaced the live certificate before the key was checked, so a
  wrong key broke the next nginx restart for every instance on the host.
- **Venv packages:** `sudo -u <user> bash -lc "… pip install '<pkg>'"` was expanded by the outer root shell
  first, so a package typed as `$(…)` ran as root. Splitting on commas also broke `babel>=2.14,<3`.
- **Report:** the server report ran the instance-owned venv interpreter (`python3 --version`) as root.
- **Neutralisation:** it ran as the PostgreSQL superuser on a database copied from another instance, so a
  trigger in that database ran with superuser rights.
- **Fixed `/tmp` names, written as root:** the venv replication used `/tmp/<target>_venv_reqs.txt`, which a local
  user could plant. The wkhtmltopdf `.deb` was downloaded, checked and installed in separate steps.
- **Filestore archives:** tar ran as root inside instance-controlled directories, both to back up and to
  restore.
- **Terminal:** escape sequences in database names, file names or command output reached the terminal, and could
  rewrite what the preview showed.
- **Smaller ones:**
  - a secret escaped inside an SQL literal was not masked;
  - a password containing `$$` broke the role SQL;
  - `git` ran as root in the instance checkout, which modern git refuses ("dubious ownership"), so a replica
    never detected its source's branch;
  - `--` was missing before typed unit names;
  - a typed carriage return reached `odoo.conf`;
  - exports followed links.

## What changes

- **Certificates:** the operator's files are staged, checked and then moved into place, quoted, with the old
  files kept as `.previous`.
- **pip:** runs as the instance user with no login shell. Root only reads the requirements file and passes it on
  stdin. Options are refused, and requirements are split on commas only before a package name.
- **Report:** reads `pyvenv.cfg` instead of running the interpreter.
- **Neutralisation and identity:** run as the copy's owner, with `SET ROLE` and a fixed `search_path`.
- **Temporary files:** a private `mktemp -d` holds the venv replication's requirements and the wkhtmltopdf
  package. The replication keeps only exact `name==version` lines, shows them, and fails when pip fails.
- **tar and git:** tar runs as the instance user, both for backups (manual and scheduled) and for restores; git
  runs as the instance user too.
- **Terminal:** host text is sanitised before it is printed, colours excepted. Typed values must not contain
  control characters.
- **Smaller ones:** `mask` covers escaped forms, the role SQL uses a unique dollar tag, typed unit names go after
  `--`, and exports are new private files that never follow a link.

## Impact

- Specs: `web-proxy-tls`, `instance-configuration`, `instance-provisioning`, `data-backup-restore`,
  `execution-safety`, `server-audit`, `addon-inventory`.
- Code: `planners.py`, `system.py`, `ui.py`, `prompts.py`, `workflows/{manage,backup_restore,report,addons,
  services,common}.py`.
- Tests: `tests/test_injection_privilege.py`. A new `tools/verify_privilege.py`, which runs in CI, executes the
  certificate, wkhtmltopdf, venv-replication and owner-role neutralisation steps.
