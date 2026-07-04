# Tasks

## 1. Spec deltas

- [x] 1.1 instance-provisioning: MODIFIED "Safe configuration defaults" (strong-by-default secrets,
      warned weak opt-out, DB user unchanged).
- [x] 1.2 instance-provisioning: ADDED "Database manager exposure control" (`list_db=False` default +
      warning).
- [x] 1.3 instance-provisioning: ADDED "Production performance tuning" (`workers=(cpu*2)+1`, RAM cap,
      per-worker memory, `limit_request`, override; detection in execution layer).
- [x] 1.4 instance-provisioning: ADDED "Database filter" (`dbfilter`).
- [x] 1.5 instance-provisioning: ADDED "PostgreSQL SSL mode for remote databases" (`db_sslmode=require`
      for remote).
- [x] 1.6 instance-provisioning: ADDED "Optional wkhtmltopdf provisioning" (patched 0.12.6 verified /
      distro fallback / skip+warn).
- [x] 1.7 instance-configuration: MODIFIED "Instance status inspection" (split into on-demand views; no
      auto-dump).
- [x] 1.8 instance-configuration: ADDED "Security and production posture audit".
- [x] 1.9 server-audit: ADDED "Production posture reporting".
- [x] 1.10 instance-provisioning: ADDED "Environment detection and version-adaptive configuration"
      (OS codename / nginx / PostgreSQL / Odoo major; gevent vs longpolling; unsupported-family + scram
      warnings).
- [x] 1.11 web-proxy-tls: MODIFIED "Proxy vhost contents" (http2 form by nginx version; live-chat
      location by Odoo major).
- [x] 1.12 `openspec validate production-defaults-and-status-audit --strict` passes.

## 2. Code — provisioning & config generation

- [x] 2.1 `system.py`: read-only probes — `detect_cpu_count()`, `detect_total_ram_bytes()`,
      `wkhtmltopdf_version()`, `detect_os_release()`, `detect_nginx_version()`, `detect_postgres_version()`.
- [x] 2.2 `models.py`: fields `list_db`/`dbfilter`/`db_sslmode`/`workers`/`max_cron_threads`/memory limits;
      `generate_secret`, `ensure_strong_secrets`, `uses_instance_name_secret`, `effective_dbfilter`,
      `odoo_major`, `is_remote_db_host`, `gevent_port_key`, `live_chat_location`; `normalize_defaults`
      no longer fills secrets with the instance name.
- [x] 2.2b `planners.py`: `_odoo_conf_content` renders `gevent_port`/`longpolling_port` by Odoo major,
      `list_db`, `dbfilter`, derived tuning, `db_sslmode` when remote; `_nginx_*` take the http2 form and
      live-chat location (builders stay pure).
- [x] 2.3 `planners.py`: `compute_worker_tuning(cpu, ram)` pure helper.
- [x] 2.4 `planners.py`: `plan_install_wkhtmltopdf(mode, codename)` with SHA-256 verify gate.
- [x] 2.4b `planners.py`: pinned codename→(asset, sha256) table + `resolve_wkhtmltopdf_asset` (unmapped →
      None; jammy verified against Odoo's published checksum).
- [x] 2.5 `prompts.py`/`install.py`: warned weak-secret opt-out; `list_db` choice with warning;
      workers/memory suggestion+override; remote `db_sslmode` choice; wkhtmltopdf three-way choice;
      nginx-version-aware vhosts.

## 3. Code — status split & posture audit

- [x] 3.1 Shared pure evaluator `posture_rows(...)` in `planners.py`, used by both the management posture
      view and the server-audit report.
- [x] 3.2 `manage.py`: no auto status dump; menu entries Status ▸ Locations / Detected resources / Config
      values / Security & production; non-destructive config update (`_load_config_from_conf`).
- [x] 3.3 `report.py`: per-instance posture matrix + host wkhtmltopdf version.

## 4. Docs & changelog

- [x] 4.1 `docs/configuration-reference.md`: `list_db` default flip, `dbfilter`, `db_sslmode`, derived
      workers/memory, wkhtmltopdf, strong-secret defaults; security note rewritten.
- [x] 4.2 `docs/installation.md` (new "## Production hardening" section) + `docs/operations/instance-management.md`
      (split status + posture; non-destructive update): new install prompts and the split status/posture views.
- [x] 4.3 `docs/server-audit.md`: posture reporting + host wkhtmltopdf version.
- [x] 4.4 Root `README.md`: friendly description + diagram (as-is) + platform note + references; supported
      platforms link; `CHANGELOG.md` `[Unreleased]`.
- [x] 4.5 New `docs/platforms.md` "What it offers & supported platforms" (capabilities + support matrix),
      linked from the README map.
- [x] 4.6 Docs English-canonical: Spanish UI menu labels replaced with English across the 9 affected pages;
      two in-code Spanish labels (`Disco (home)`/`Disco (data dir)`, `Otros`) migrated to English + i18n;
      CLAUDE.md language convention clarified (English canonical, Spanish via i18n) + README maintenance rule.

## 5. Verify

- [x] 5.1 `openspec validate --strict`, `ruff`, `pytest` (93 passed), `compileall` all pass.
- [x] 5.2 Dry-run checks: `odoo.conf` renders `list_db=False`, `dbfilter`, derived `workers`, `db_sslmode`
      only when remote, `gevent_port`/`longpolling_port` by major; nginx http2 form by version; wkhtmltopdf
      checksum gate present; posture flags a legacy instance (unit tests in `tests/test_production_defaults.py`).
