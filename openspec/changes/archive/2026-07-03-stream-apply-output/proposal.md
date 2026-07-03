# Stream command output during apply

## Why

When a confirmed plan is applied, each command's output was captured and printed only **after** the command
finished. Long steps — `apt-get install`, `pip install -r requirements.txt`, `git clone`, `pg_restore` of a
large dump — therefore sat completely silent for minutes, giving the operator no sign of progress and no way
to tell a slow command from a hung one.

## What changes

Add `system.run_streaming(command)` and use it in `apply_commands`. It runs the command with
`subprocess.Popen`, forwards combined stdout/stderr **live** line by line while also capturing it, and returns
a `CompletedProcess` so the existing stop-on-error logic is unchanged. stdin is closed (`DEVNULL`) so a command
can never block waiting for input.

- **stdlib only** — `subprocess.Popen`/`PIPE`/`STDOUT`/`DEVNULL`/`CompletedProcess`; the project keeps
  `dependencies = []` (a hard project constraint: no packages beyond the Python standard library).
- The read-only `run()` used for existence checks, discovery, and listing is **unchanged** (it still captures
  output for parsing; those commands are fast and their output is not shown live).

## Impact

- Affected code: `instance_manager/system.py` (`run_streaming` added; `apply_commands` streams).
- Affected spec: `execution-safety` — the apply step streams output live.
- New `tests/test_system.py` (guarded to run only where `bash -lc` actually works, e.g. CI on Ubuntu).
- No change to which commands run, the plan/preview/confirm flow, or any phrase confirmation.
