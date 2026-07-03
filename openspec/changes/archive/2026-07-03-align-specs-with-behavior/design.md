# Design

## Principle

This change makes the written record match the code. Where a claim was too strong, it is qualified to what the
code actually guarantees; where behavior was undocumented, it is added. The default resolution for each audit
finding is "adapt the doc to the code", except two cases where the code itself was wrong about its target
platform/UI and is corrected instead.

## Spec edits (delta MODIFIED requirements)

Each modified requirement keeps its existing scenarios and adds/edits the ones needed for accuracy:

- **execution-safety / Automatic cleanup** — reword the DB-role clause to "in the PostgreSQL-install modes …
  even if it pre-existed" and add an Odoo-only scenario, matching the per-mode `cleanup_db_role` flag.
- **instance-provisioning / Odoo base setup** — the autostart-off scenario states "disables autostart, then
  starts", matching the explicit `systemctl disable` + `start`.
- **instance-configuration** — status TLS list gains "incomplete"; the update requirement gains a scenario
  stating it replays the full base-setup plan.
- **data-backup-restore** — restore gains a "local-only existence check" scenario; duplication gains a
  "does not provision the target instance" scenario (the filestore-location scenario already landed in the
  data-operation-bugs change).
- **server-audit** — system overview includes PostgreSQL/Nginx service state + `nginx -t`; discovery names the
  legacy conf path; the read-only requirement is reworded to "read-only with respect to server configuration"
  with scenarios for the optional export and optional active TLS checks.
- **fail2ban-protection** — base setup notes the UFW runtime prerequisite; real-IP assessment states the
  300-line / IPv4-only / unknown-does-not-gate behavior.

## Two code corrections (not behavior redesign)

- **Prompt wording** — `workflows._collect_instance_config` asked for the app-server IP "para pg_hba/UFW", but
  no UFW rule is ever generated (`app_server_ip` only feeds the `pg_hba` line). Reworded to avoid implying a
  firewall change the tool does not make.
- **Package name** — `plan_odoo_base_setup` installed `libtiff5-dev`, which does not exist on Ubuntu 24.04
  (renamed to `libtiff-dev`), so the first `apt-get install` would fail on the tool's own target OS. Switched
  to `libtiff-dev`, which resolves on 22.04 and 24.04. This is the one change that alters an emitted command.

## Verification

The eunomai `docs-check` keeps README↔docs links and frontmatter honest; `openspec validate --specs` keeps the
edited specs well-formed. `ruff`/`pytest`/compile confirm the two code edits are clean. No new tests are needed
(no new logic); the existing suite still passes.

## Out of scope

Actual behavior improvements the audit implied — pre-populating the config-update prompts from the current
conf (instead of class defaults), or installing/checking UFW — are deferred: the prompt-defaults fix belongs
with `improve-operator-ux`, and auto-managing UFW is a feature decision, not an alignment fix.
