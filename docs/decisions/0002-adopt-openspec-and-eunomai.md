---
type: decision
title: "ADR 0002 — Adopt OpenSpec + eunomai for specs, docs, and safe controls"
description: "Why the project adopts OpenSpec for spec-driven development and the eunomai conventions for docs and guardrails."
tags: [process, sdd, docs, adr]
updated: 2026-07-03
---

# ADR 0002 — Adopt OpenSpec + eunomai for specs, docs, and safe controls

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The project began as working code (a layered, root-run Odoo administration CLI) with only a short Spanish
README and no captured requirements, no contributor guide, and no structural checks. As the surface grows
(installation, lifecycle, security, audit), behavior needs a durable, reviewable source of truth, and changes
to a root-run tool warrant a deliberate, spec-first process.

## Decision

Adopt two complementary, low-lock-in layers:

- **OpenSpec** (`openspec/`) as the spec-driven-development engine. Behavior is captured as capability specs
  under `openspec/specs/`; non-trivial changes flow through `/opsx:explore → /opsx:propose → /opsx:apply →
  /opsx:archive`, with proposals and spec deltas under `openspec/changes/`.
- **eunomai** conventions for the surrounding layer: a routable `docs/` living-documentation standard
  (flat pages with `type`/`title`/`description` frontmatter and a product-shaped README map), community-health
  files, a `CLAUDE.md` agent guide, and safe-controls (runtime `PreToolUse` hooks from the eunomai plugin plus
  a native `permissions` baseline).

The initial specs were **reverse-engineered from the existing behavior** to establish a baseline, then kept
current through the change flow going forward.

## Alternatives considered

- **Do nothing / keep only the README.** Rejected: no reviewable record of behavior for a high-consequence
  tool, and no gate against docs drifting from code.
- **A bespoke docs/specs structure.** Rejected: reinventing conventions that OpenSpec + eunomai already
  provide, with checks, for free.

## Consequences

- **Positive:** behavior is documented and validated (`openspec validate --specs`); docs structure and
  provenance are gated by read-only checks; new contributors get a clear spec-first workflow.
- **Cost:** a spec-first step for non-trivial changes and the discipline of keeping specs and docs in sync
  with code.
- **Lock-in:** minimal — everything seeded lives in the project's own files (Markdown + OpenSpec), so removing
  either layer leaves a working project.
