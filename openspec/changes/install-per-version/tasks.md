# Tasks

## 1. Spec deltas

- [x] 1.1 instance-provisioning, instance-configuration, data-backup-restore deltas; `--strict` passes.

## 2. Code

- [x] 2.1 `support.py`: matrix, interpreter choice, setuptools pins, substitutes, uv pin, core URLs.
- [x] 2.2 `InstanceConfig`: `core`, `python`, `python_source`, `data_dir`.
- [x] 2.3 Planners: venv by interpreter, uv install and Python, clone by core, `odoo.conf` defaults, unit,
      PostgreSQL floor, unattended apt, merged `odoo.conf` and update plan.
- [x] 2.4 Install flow: supported version, branch from version, core, runtime, local DB opens nothing,
      cleanup keeps a data dir that holds a filestore.
- [x] 2.5 Replica: source core, version's interpreter, managed data dir.
- [x] 2.6 Update configuration: merge, no reinstall, role password, restart, detected version/domain.
- [x] 2.7 i18n entries.

## 3. Verify

- [x] 3.1 Unit tests, ruff, `tools/verify_install_runtime.py` (Odoo 14 on uv's 3.8, Odoo 16 on the host's 3.12,
      negative control without the setuptools pin).

## 4. Docs

- [x] 4.1 Platforms matrix, installation, configuration reference, instance management, changelog, contributing.
