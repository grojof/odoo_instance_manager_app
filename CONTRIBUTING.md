# Contributing

Thanks for helping improve Odoo Instance Manager. This project manages production Odoo servers, so changes
are held to a careful, spec-first standard.

## Ground rules

- **Spec-first for non-trivial changes.** New behavior or changes to existing behavior are captured as an
  OpenSpec change before code. See [Workflow](#workflow) below and
  [`docs/architecture.md`](docs/architecture.md) for how the layers fit together.
- **Never weaken a safety control to make something work.** The preview → confirm → apply gate, phrase
  confirmations, and identifier validation are load-bearing (see
  [`docs/decisions/0001-plan-preview-apply-safety.md`](docs/decisions/0001-plan-preview-apply-safety.md)).
- **Keep planners pure.** Functions in `planners.py` build `list[Command]` and must not execute anything or
  perform I/O. Execution lives in `system.py`; orchestration in `workflows.py`.
- **Validate and quote every operator-supplied value** that reaches a shell command or SQL string. Use the
  existing `_quote`/`shlex.quote` and the identifier validators — do not interpolate raw input.

## Project layout

| Path | Role |
|------|------|
| `odoo_instance_manager.py` | Entry point, root check, main menu |
| `instance_manager/models.py` | `InstanceConfig`, identifier validation, path derivation |
| `instance_manager/planners.py` | Pure command-plan builders (config/systemd/nginx/fail2ban) |
| `instance_manager/system.py` | Execution primitives, existence checks, preview/apply |
| `instance_manager/prompts.py` | Interactive input, file picker, phrase confirmation |
| `instance_manager/ui.py` | Terminal rendering |
| `instance_manager/workflows.py` | Menus, plan assembly, discovery/audit |
| `openspec/specs/` | Capability specifications (the source of truth for behavior) |
| `docs/` | User- and operator-facing documentation |

## Conventions

- Python 3.12+, `from __future__ import annotations`, standard library only (no third-party runtime deps).
- Files are UTF-8 with LF newlines and a final newline.
- Conventional Commits in the imperative mood; one logical change per commit. No AI-attribution trailers.
- Match the surrounding style: small functions, early returns, type hints, Spanish operator-facing strings.

## Workflow

For non-trivial changes, use the OpenSpec flow:

```
/opsx:explore        # think through the change (optional)
/opsx:propose <name> # create the change: proposal, design, tasks, spec deltas
/opsx:apply          # implement the tasks
/opsx:archive        # fold the spec deltas into openspec/specs/ and archive
```

Validate specs and changes at any time:

```bash
openspec validate --specs
openspec list --specs
```

## Before opening a PR

- Run the tool against a **disposable VM or container**, never a production host, to exercise the affected
  menu path end to end.
- Confirm the affected capability spec under `openspec/specs/` still matches the behavior (update it via a
  change when behavior shifts).
- Keep the docs honest: if behavior changes, update the affected `docs/` page and the README map in the same
  change.
