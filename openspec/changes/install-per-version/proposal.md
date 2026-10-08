# Install each Odoo version the way it needs

## Why

The install used the host `python3` and the newest setuptools for every Odoo version, and always cloned
official Odoo. On Ubuntu 24.04 (Python 3.12) Odoo 14 does not install (its requirements stop at 3.10), Odoo 14-16
do not start with setuptools 81+ (they import `pkg_resources`, which setuptools 81 removed), Odoo 17-19 cannot
be installed on a 3.9 host, and Odoo 16-19 pin a gevent for 3.10 that pip cannot build. There was no way to run
OCA's OCB. New databases got demo data (Odoo <= 18 loads it unless told not to), the filestore lived inside the
instance home, "Odoo + PostgreSQL" opened PostgreSQL to the network although both run on one host, apt could
stop on a prompt, and *Update existing configuration* replaced `odoo.conf` (losing `data_dir`, `smtp_*`, extra
addons paths), re-ran apt and pip (moving setuptools under an Odoo that needs it pinned), did not restart the
service, and never changed the role's password.

## What changes

- **Support matrix** (`instance_manager/support.py`): per Odoo 12-19, the Python range with its evidence tier,
  the interpreter to use when the host's cannot build the version, the PostgreSQL floor; the facts odoo_dwg
  keeps and verified by building and starting every version on Ubuntu 24.04.
- **Interpreter per version**: the host `python3` when it can build the version, else a uv-provided CPython
  (uv pinned and SHA-256-checked, interpreters in a shared root-owned `/opt/odoo-python`).
- **setuptools per version**: `<58` up to 13, `<81` up to 16; Odoo 12's `pyldap` replaced by `python-ldap`.
- **Core choice**: official Odoo or OCB; a replica runs the source's core.
- **Production defaults**: `without_demo = all` up to Odoo 18; `data_dir = /var/lib/odoo/<instance>` for new
  installs; unit after Odoo's own (`KillMode=mixed`, ordered after a local PostgreSQL); PostgreSQL floor checked.
- **Odoo + PostgreSQL on one host** opens nothing to the network.
- **apt** runs unattended and waits for the dpkg lock.
- **Update existing configuration** merges `odoo.conf`, reinstalls nothing, sets a new password on the local
  role, restarts a running service, and reads the version and domain from the instance.

## Impact

- Specs: `instance-provisioning`, `instance-configuration`, `data-backup-restore`.
- Code: `support.py` (new), `models.py`, `planners.py`, `system.py`, `workflows/{install,manage,backup_restore}.py`,
  `i18n.py`.
- Tests: `tests/test_install_per_version.py`; `tools/verify_install_runtime.py` builds real venvs.
- Docs: `docs/platforms.md`, `docs/installation.md`, `docs/configuration-reference.md`,
  `docs/operations/instance-management.md`, `CHANGELOG.md`, `CONTRIBUTING.md`.
