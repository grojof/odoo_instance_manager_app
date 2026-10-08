# Provisioning facts, re-derived from their sources

## Why

The fact audit checked every hard-coded version, flag and package against its primary source: Odoo's
checkouts, PyPI, nginx.org, the wkhtmltopdf release, and runs of the real tools. These were false or risky:

- **gevent 21.8.0.** It has no wheel for Python 3.10 or 3.11, and its source no longer builds. Odoo 14 pins it
  for every interpreter above 3.9, and Odoo 15 for 3.10 and 3.11; only 16–19 (3.10) were avoided. So Odoo 15
  did not install on Debian 12 (Python 3.11).
- **Python maxima.** Odoo 15–18 state `MIN_PY_VERSION`/`MAX_PY_VERSION` in `odoo/__init__.py`. Odoo 16's maximum
  is 3.12, not the 3.13 derived earlier, so 16 was built on Debian 13's 3.13.
- **setuptools.** It removed `pkg_resources` in 82, not 81. The `<81` pin is still right, but its reason was
  wrong.
- **PostgreSQL 13** (Debian 11) stores passwords as md5 by default. The scram `pg_hba` rule the tool writes then
  refuses the app server.
- **nginx.**
  - The version was detected before nginx was installed, so it was unknown and treated as new. On 22.04 and
    Debian 11 the first HTTPS install then wrote `proxy_cookie_flags` for nginx 1.18, and `nginx -t` failed.
  - The directive appeared in 1.19.3, not 1.19.8.
- **odoo.conf merge.**
  - It lifted other sections into `[options]` and cut multi-line values to their first line.
  - It wrote a key twice when its case differed, which Odoo's parser rejects.
- **Local PostgreSQL steps.**
  - Local `psql` ignored the port.
  - Remote access ran `sed` on `postgresql.conf`, which `conf.d` overrides.
  - It restarted PostgreSQL even when nothing changed.
- **uv.** `command -v uv` accepted any uv on root's PATH, and the instance user's `secure_path` holds none.
- **wkhtmltopdf.**
  - The pinned packages were amd64 only, although upstream builds arm64.
  - The distribution package was offered where there is none (Debian 13, Ubuntu 26.04).
- **An existing role.** It was reused with its old password while `odoo.conf` got the new one, so the install
  always failed.

## What changes

- **Python matrix.** Official maxima for 15–18 (16 is 3.12). The gevent 21.8.0 rows are listed per branch, and
  uv's interpreter is used for those hosts.
- **PostgreSQL passwords.** `password_encryption = 'scram-sha-256'` is set whenever a password is set. An
  existing role's password is either set or kept, as the operator chooses.
- **Local PostgreSQL steps.** Local `psql -p <port>`. Remote access uses `ALTER SYSTEM`, restarts only on a
  change, reads the value back, and reloads for `pg_hba`.
- **Database login check.** It uses `odoo.conf`'s SSL mode and the instance user's CA.
- **nginx.** The version is the installed one or apt's candidate; unknown counts as old. `proxy_cookie_flags`
  from 1.19.3.
- **odoo.conf.** It is read as Odoo reads it, other sections are kept, and multi-line values are written back.
- **uv.** It is called at `/usr/local/bin/uv` with its version checked, and installs interpreters with `--no-bin`.
- **wkhtmltopdf.** Assets keyed by codename and machine, the arm64 checksums computed, and the distro package
  offered only when apt has one.
- **Smaller fixes.**
  - The gevent port must differ from the HTTP port.
  - The CLI hint creates a database as the instance user.
  - The unused PostgreSQL version probe is removed.

## Impact

- Specs: `instance-provisioning`, `web-proxy-tls`, `instance-configuration`.
- Code: `support.py`, `planners.py`, `system.py`, `workflows/{install,manage}.py`.
- Tests: `tests/test_provisioning_facts.py`.
- Verification:
  - `tools/verify_postgres_setup.py` (CI) runs the PostgreSQL steps against a cluster on another port that
    stores md5 by default and has a `conf.d`;
  - `tools/verify_secrets.py` checks scram storage;
  - `tools/verify_install_runtime.py` checks the uv path and its skip.
