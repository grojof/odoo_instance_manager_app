# Tasks

## 1. Spec deltas

- [x] 1.1 web-proxy-tls, instance-configuration, instance-provisioning, data-backup-restore, execution-safety,
      server-audit, addon-inventory.
- [x] 1.2 `openspec validate --specs` passes.

## 2. Code

- [x] 2.1 Certificates staged, checked, moved; quoted paths and subject.
- [x] 2.2 Venv pip as the instance user, stdin requirements, option refusal, comma split.
- [x] 2.3 Report reads `pyvenv.cfg`; git as the instance user; OCB origin forms.
- [x] 2.4 Neutralisation and identity under `SET ROLE` with a fixed `search_path`.
- [x] 2.5 Private temporary directories (venv replication, wkhtmltopdf); tar as the instance user.
- [x] 2.6 `sanitize` for host text; control characters refused in prompts; `--` before unit names.
- [x] 2.7 `mask` escaped forms; unique dollar tag; `run(check=True)` error without the command; private
      exports; `SECURITY.md`.
- [x] 2.8 i18n entries.

## 3. Verification

- [x] 3.1 Unit tests (`tests/test_injection_privilege.py`).
- [x] 3.2 `tools/verify_privilege.py` (CI): certificates with real openssl, wkhtmltopdf and venv replication with
      stubs, owner-role neutralisation against a PostgreSQL of its own with a superuser negative control.
