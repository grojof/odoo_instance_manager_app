---
type: reference
title: "Safe controls"
description: "Runtime guardrails (eunomai PreToolUse hooks) and the recommended permissions baseline for this repo."
tags: [safe-controls, hooks, security, permissions]
audience: [contributor]
updated: 2026-07-03
---

# Safe controls

Two layers protect work *on this repository* (distinct from the tool's own runtime safety, which is the
preview → confirm → apply gate described in
[`decisions/0001-plan-preview-apply-safety.md`](../decisions/0001-plan-preview-apply-safety.md)):

1. **Content-aware PreToolUse hooks** — contributed by the installed **eunomai** Claude Code plugin.
2. **Static path permissions** — native Claude Code `permissions` in `.claude/settings.json`.

## PreToolUse hooks (from the eunomai plugin)

The eunomai plugin registers `PreToolUse` hooks matching `Bash|PowerShell`. On each shell command they decide:

| Control | Decision | What it catches |
|---------|----------|-----------------|
| Commit-trailer guard | **deny** | `git commit` messages carrying AI-attribution trailers. The only hard block. |
| Safety gate | **ask** | Irreversible / sensitive commands: force-push, recursive force deletes (`rm -rf`), version bumps, and access to secrets / auth / `.env` / SSH keys. |

Posture: **ask-by-default** (the human stays in control), **fail-open** (a hook error never blocks work). It
is a floor-raiser, **not** a security boundary. Because these hooks ship with the plugin, this repository does
**not** vendor its own copy of the hook scripts — nothing to maintain here.

This matters especially in this project: the manager is designed to run as **root** and to generate
`rm -rf`, `dropdb`, `userdel`, and `DROP ROLE` commands. When developing or testing those flows, expect the
safety gate to ask before your shell runs a matching command.

## Recommended permissions baseline

Static path rules use Claude Code's native `permissions`, already seeded in
[`../.claude/settings.json`](../../.claude/settings.json):

```json
{
  "permissions": {
    "deny": [
      "Read(**/.env)",
      "Read(**/.env.*)",
      "Read(**/*.pem)",
      "Read(**/*.key)",
      "Read(**/id_rsa)",
      "Read(**/id_ed25519)"
    ],
    "ask": [
      "Read(**/secrets/**)",
      "Read(**/credentials/**)",
      "Edit(**/.env)",
      "Edit(**/.env.*)"
    ]
  }
}
```

`deny` blocks outright; `ask` escalates to you. Treat this as a baseline to extend, not an exhaustive list —
for example, add rules for any local dumps or filestore archives you keep outside the repo.
