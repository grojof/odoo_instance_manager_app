# Design

## Packaging

`setuptools` build backend (stdlib-only runtime, so `dependencies = []`). The repository is a top-level module
plus one package, declared explicitly so the build is unambiguous:

```toml
[tool.setuptools]
py-modules = ["odoo_instance_manager"]
packages = ["instance_manager"]
```

The console entry point maps `odoo-instance-manager` → `odoo_instance_manager:main`; `main()` already returns
an int, which setuptools wraps as the process exit code. License is declared with the SPDX expression
`AGPL-3.0-or-later` (the repo ships the AGPLv3 text in `LICENSE`).

Dev tooling is an optional extra (`.[dev]`) so a plain install stays dependency-free while contributors get
`pytest` + `ruff` with one command.

## Ruff ruleset

`select = ["E", "F", "I", "UP", "B", "W"]` with `ignore = ["E501"]`, `line-length = 100`,
`target-version = "py312"`. Rationale:

- `F`/`B` catch real bugs; the codebase already has **zero** F findings.
- `I`/`UP` keep imports sorted and syntax modern (8 safe autofixes applied once, up front).
- `E501` is deferred, not because long lines are fine in general, but because ~200 of them are embedded
  `bash -lc` / SQL command strings (up to ~196 cols) that would be *less* readable — and riskier to edit — if
  wrapped. New code should still target ≤100 cols; E501 can be enabled per-file later once the command strings
  are extracted (a candidate for the `refactor-workflows-module` change).

## CI

One `ubuntu-latest` job (mirrors the tool's target OS) runs the full gate in order: install → ruff → pytest →
byte-compile → `openspec validate --specs` → eunomai `docs-check`/`provenance-check`. The eunomai checks need
the CLI bundle, so the workflow checks out `grojof/eunomai` pinned at `v0.4.0` into `.eunomai` and runs
`node .eunomai/tools/dist/cli.cjs …` from the project root — the pattern documented in eunomai's own
`docs/checks.md`. OpenSpec is pinned to `@fission-ai/openspec@1.4.1` to match the version the specs were
authored against.

## Why not enforce E501 now / rewrap the command strings

Rewrapping 200+ lines in a CI-onboarding PR would bury the meaningful change in noise and risk altering shell
command semantics (a stray break inside a heredoc or a quoted argument changes behavior). Extracting command
strings into named builders is real work that belongs in the refactor change, behind the test net this change
establishes.
