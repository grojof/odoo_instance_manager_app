---
type: decision
title: "ADR 0001 — Plan / preview / confirm / apply as the safety model"
description: "Why every host-mutating action assembles a command plan, previews it, and applies only after confirmation."
tags: [architecture, safety, adr]
updated: 2026-07-03
---

# ADR 0001 — Plan / preview / confirm / apply as the safety model

- **Status:** Accepted (documents the established design)
- **Date:** 2026-07-03

## Context

The tool runs as **root** on production Odoo servers and performs high-consequence operations: installing
packages, writing systemd units and Nginx vhosts, creating and dropping PostgreSQL roles and databases,
deleting Linux users, and removing filestore data. A single wrong instance name or a raw shell interpolation
could destroy the wrong instance or open an injection path.

## Decision

Every host-mutating action follows one pipeline:

1. **Plan** — pure builders in `planners.py` (and inline assembly in `workflows.py`) produce an ordered
   `list[Command]`, where each `Command` is a `(description, command)` pair. Building a command never runs it.
2. **Preview** — `preview_commands` renders the full, numbered plan to the operator before anything executes.
3. **Confirm** — the operator explicitly confirms; **destructive or data-altering** actions additionally
   require typing an exact phrase (e.g. `ELIMINAR <instance>`, `RESTORE <instance>`, `DUPLICAR <instance>`,
   `ELIMINAR-TODO <instance>`) via `confirm_with_phrase`.
4. **Apply** — `apply_commands` runs the plan, re-checking root first; on a failed install a best-effort
   cleanup removes that instance's residues so the operation can be retried cleanly.

Supporting invariants:

- **Identifier validation** — instance and PostgreSQL identifiers are checked against strict regexes
  (`INSTANCE_NAME_RE`, `POSTGRES_IDENTIFIER_RE`) before any command is built.
- **Quoting** — operator-supplied values are passed through `shlex.quote` / `_quote` when interpolated into
  shell or SQL.

These properties are captured as the `execution-safety` capability spec in
[`../../openspec/specs/execution-safety/spec.md`](../../openspec/specs/execution-safety/spec.md).

## Consequences

- **Positive:** the operator always sees exactly what will run; a typo is caught at preview, not after damage;
  the pure planner layer is trivially testable and reviewable; injection surface is contained at the boundary.
- **Cost:** every new host-mutating feature must route through the plan/preview/apply flow rather than calling
  `run()` directly, and destructive additions must define a confirmation phrase. This is a deliberate tax.
- **Non-negotiable:** contributors must not add a code path that mutates the host without a previewed plan, and
  must not weaken a confirmation to "make it work" (see `CONTRIBUTING.md`).
