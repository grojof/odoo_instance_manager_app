# Design — production defaults, wkhtmltopdf, status audit

## Context

Debian/Ubuntu-family target (validated on Ubuntu 24.04, but no longer *pinned* to it). Rather than
assume one stack, the tool detects each version-sensitive component and renders accordingly. Standard-
library-only holds: secret generation uses `secrets`; all detection and checksum verification are
shell probes, not Python deps.

## Environment detection (new, cross-cutting)

Cheap probes run once in the execution layer (`system.py`) and feed both the pure planners (as passed-in
values) and the audit. Each is a single command; total added cost is negligible.

| Component | Probe | Drives |
|---|---|---|
| OS family + codename | `/etc/os-release` (`ID`, `VERSION_CODENAME`) | wkhtmltopdf asset choice; "unsupported OS family" warning (non-apt → skip package steps) |
| nginx version | `nginx -v` → `nginx/<x.y.z>` | http2 directive form in the vhost |
| PostgreSQL version | `SHOW server_version` (already connect as postgres) | `scram-sha-256` support check (≥ 10); surfaced in audit |
| Odoo major | operator-supplied `version`/`repo_branch` (already collected) | `gevent_port` vs `longpolling_port`; nginx live-chat location |

Detection only *decides between correct options*; it never invents unsupported config. When a component
is newer/older than anything known, the tool falls back to the safest known form and logs what it
assumed.

### nginx http2 — verified

`http2 on;` was added in nginx **1.25.1**; on older nginx it does not exist and breaks `nginx -t`. The
`listen … http2` parameter is the correct form on < 1.25.1 and is only *deprecated* (warning, still
works) on ≥ 1.25.1. Rule: nginx ≥ 1.25.1 → `listen … ssl;` + `http2 on;`; otherwise → `listen … ssl
http2;`. (Ubuntu 24.04 ships 1.24 → old form; Ubuntu 26.04 will ship ≥ 1.26 → new form — both handled.)

### Odoo live-chat/bus — verified

Odoo **16.0** renamed `longpolling_port` → `gevent_port` and moved the proxy location `/longpolling/poll`
→ `/websocket` (both still proxy to the gevent port). Rule keyed on the Odoo major:
- odoo.conf: Odoo ≥ 16 → `gevent_port = <p>`; Odoo ≤ 15 → `longpolling_port = <p>`.
- nginx location: Odoo ≥ 16 → `/websocket`; Odoo ≤ 15 → `/longpolling/poll`.

This fixes a latent bug: the current unconditional `gevent_port` + `/websocket` breaks live-chat on
Odoo ≤ 15.

### PostgreSQL — scope note

The generated PostgreSQL changes (`listen_addresses`, a `pg_hba` scram line) already resolve paths via
`SHOW config_file` / `SHOW hba_file`, so they are version-agnostic. `scram-sha-256` requires PG ≥ 10;
every Ubuntu ≥ 20.04 ships ≥ 12, so detection here is a **validation/audit** signal (warn if < 10), not
a config branch. Performance tuning of `postgresql.conf` (shared_buffers, work_mem, …) is deliberately
**out of scope** — a separate, larger change.

## Decisions grounded in official sources

### 1. Master/DB password — strong by default, warned opt-out

Odoo's deploy guide: the master password "should be set to a randomly generated value" and can be
generated with `python3 -c 'import base64, os; print(base64.b64encode(os.urandom(24)))'`.

- Generate with stdlib `secrets.token_urlsafe(24)` (equivalent entropy, no external command).
- The install prompt shows the generated secret as the **accepted-by-default** value (Enter accepts
  it). Typing a weak value — including the instance name — is allowed only after an explicit warning.
- **Hashing:** Odoo hashes `admin_passwd` when it is changed from the web UI (pbkdf2). At install we
  write a strong **plaintext** value (Odoo reads plaintext fine and will re-hash on the next UI
  change). We do **not** pre-hash (would pull in passlib/odoo internals — out of the stdlib budget).
  The posture audit treats a value that looks hashed (`$…`) as acceptable and only flags the
  instance-name plaintext as guessable. This matches the operator's stated workflow: plaintext-strong
  now, hashed later via the GUI.

### 2. Database manager — `list_db = False` recommended

Odoo: "strongly recommended to block access to the database manager screens … use the
`--no-database-list` startup parameter", and "disable the Database Manager for any internet-facing
system".

- Recommended default `list_db = False`. Implication surfaced in the prompt: the web DB-manager
  (create/duplicate/drop/restore) is then unavailable; the first database is created via CLI
  (`odoo-bin -d <db> -i base --stop-after-init`) or by temporarily re-enabling the manager.
- Keeping `list_db = True` is allowed after a warning that DB listing/creation/deletion become
  reachable over HTTP, gated only by the master password.

### 3. `dbfilter`

Odoo: "Setting a proper `--db-filter` is an important part of securing your deployment"; required for
multi-DB and Website. Default written: `^<db_name>$` when the DB name is known, else host-based
`^%d$`. Regex-anchored, exact.

### 4. Workers & memory — derived from the host

Odoo forum/deploy guidance: `workers = (cpu * 2) + 1`; `max_cron_threads` separate; memory sized per
worker.

- Detect CPU via `nproc`, RAM via `/proc/meminfo`, **in the execution layer** (`system.py`); planners
  remain pure and receive the numbers.
- `workers = (cpu * 2) + 1`, then capped so `(workers + max_cron_threads) * per_worker_ram` fits
  `total_RAM − reserve(OS+PostgreSQL)`; floor of 2 for a production host, and `workers = 0`
  (threaded/dev mode) offered explicitly for tiny hosts.
- Keep the existing `limit_memory_soft = 2 GiB`, `limit_memory_hard ≈ 2.5 GiB` **per worker** shape;
  `limit_time_cpu`/`limit_time_real` unchanged; `limit_request = 8192` added. All shown as suggested
  values the operator can override.

### 5. `db_sslmode` for remote PostgreSQL

Odoo (since 11.0): `db_sslmode ∈ {disable, allow, prefer, require, verify-ca, verify-full}`, default
`prefer` (allows silent fallback to cleartext). The tool already supports a remote DB host
(`listen_addresses='*'` + host-scoped `pg_hba`).

- When `db_host` is remote (not empty/`false`/`localhost`/`127.0.0.1`/`::1`/socket), write
  `db_sslmode = require` (default); offer `verify-full` (needs a CA/cert) and weaker modes with a
  trade-off note. Local hosts: leave Odoo's default (no key written).

### 6. wkhtmltopdf — optional, patched build recommended

Odoo 18 requires wkhtmltopdf > 0.12.2 and recommends the **Qt-patched 0.12.6** build; the Ubuntu
package is un-patched (broken headers/footers, page breaks).

**Asset reality:** the `wkhtmltopdf/packaging` repo was **archived (read-only) in Aug 2023**; the newest
release `0.12.6.1-3` ships only a **bookworm** amd64 `.deb`, and there is **no `noble` asset**. So
"one asset per codename" is not fully available. Approach: keep a small **pinned table** mapping the
detected codename → best known-good asset (each with its own SHA-256), e.g. `focal`, `jammy`,
`bookworm` from releases `0.12.6-1` / `0.12.6.1-2` / `0.12.6.1-3`; map codenames without a native asset
(e.g. `noble` = 24.04) to the closest ABI-compatible build (jammy or bookworm, both run on 24.04).

- Three-way choice at install:
  1. **Recommended:** download the pinned patched `.deb` for the detected codename, **verify its
     SHA-256** against the pinned checksum, then `apt-get install -y ./<file>.deb` (pulls its own deps).
  2. **Fallback:** `apt-get install -y wkhtmltopdf` (distro, un-patched) — labelled reduced-fidelity.
  3. **Skip** — warned that PDF report generation fails until installed.
- The pinned version/codename→URL/SHA-256 table lives in the implementation, not the spec (the spec
  states behavior: detect codename, verify checksum, offer fallback + skip).
- Security (tool runs as root): never install an unverified download; the checksum gate is mandatory
  for option 1. If the detected codename has no mapped asset and no compatible fallback, the tool
  recommends the distro package or skip rather than guessing a URL.

## Status split & posture audit (UX)

`manage_existing_instance` currently calls `_show_instance_status` (three tables) every loop. New shape:

- The menu no longer auto-dumps status. Instead, discrete entries: **Estado ▸ Ubicaciones**,
  **Estado ▸ Recursos detectados**, **Estado ▸ Valores de configuración**, **Estado ▸ Seguridad y
  producción** (new). A one-line health/posture summary may head the menu, but not the full tables.
- The posture view and the server-audit report share one pure evaluator that reads `odoo.conf` +
  host probes and returns `(check, state ∈ {OK,WARN,INFO}, rationale)` rows for: `list_db`, guessable
  `admin_passwd`/`db_password`, wkhtmltopdf presence/version, workers vs CPU/RAM, remote `db_sslmode`,
  `dbfilter`, and (already OK) `proxy_mode`.

## Risks / trade-offs

- `list_db = False` by default surprises operators who create the first DB from the web manager →
  mitigated by the prompt's explicit CLI instructions and the warned opt-out.
- Random master password by default → the value is shown once in the plan preview and written to the
  `640 root:<instance>` config; operators must record it. The plan preview already displays it.
- Downloading a `.deb` is a new outbound-network action → gated behind an explicit operator choice and
  a mandatory checksum; skippable.

## Sources

- Odoo 18 — System configuration (deploy):
  https://www.odoo.com/documentation/18.0/administration/on_premise/deploy.html
- Odoo — worker number calculation:
  https://www.odoo.com/forum/help-1/odoo-worker-number-calculation-for-multiprocessing-172597
- Odoo 16 — `longpolling_port` deprecated alias of `gevent_port` (and `/websocket` from 16.0):
  https://www.odoo.com/forum/help-1/deprecationwarning-the-longpolling-port-is-a-deprecated-alias-to-the-gevent-port-option-please-use-the-latter-214918
- wkhtmltopdf packaging releases (archived Aug 2023):
  https://github.com/wkhtmltopdf/packaging/releases
- Odoo 18 on Ubuntu 24.04 (wkhtmltopdf patched build):
  https://www.soladrive.com/support/knowledgebase/5171/How-to-install-Odoo-18-on-Ubuntu-24.04.html
- nginx `http2 on` directive (added 1.25.1; `listen … http2` deprecated later):
  https://nginx.org/en/docs/http/ngx_http_v2_module.html
