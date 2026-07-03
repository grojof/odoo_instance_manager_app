# Tasks

- [x] 1.1 Add `system.run_streaming` (stdlib `subprocess.Popen`; merge stderr→stdout; `stdin=DEVNULL`; return
  a `CompletedProcess`).
- [x] 1.2 `apply_commands` streams via `run_streaming`; keep the stop-on-error behavior; leave `run()`
  capturing for probes/discovery.
- [x] 1.3 `execution-safety` spec: apply streams output live.
- [x] 1.4 Add `tests/test_system.py` (guarded on a working `bash -lc`).
- [x] 1.5 Confirm `pyproject.toml` keeps `dependencies = []` (stdlib-only).
- [x] 1.6 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally (streaming tests run in CI).
- [ ] 1.7 (operator) On a disposable VM: confirm a long step (e.g. `pip install -r requirements.txt`) streams
  output live during an install.
