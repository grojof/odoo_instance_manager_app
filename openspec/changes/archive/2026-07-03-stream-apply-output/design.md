# Design

## run_streaming

```python
def run_streaming(command: str) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        ["bash", "-lc", command],
        stdin=subprocess.DEVNULL,      # never block waiting for input
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,      # merge so combined output streams in order
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    captured = []
    for line in process.stdout:        # blocks per line -> live forwarding
        print(line, end="", flush=True)
        captured.append(line)
    process.stdout.close()
    return subprocess.CompletedProcess(process.args, process.wait(), "".join(captured), "")
```

Decisions:

- **Merge stderr into stdout.** Many tools (apt, git, pip) write progress to stderr; merging shows a single,
  correctly-ordered live stream. `apply_commands` no longer prints stdout/stderr separately after the fact —
  the stream already showed everything; on a non-zero exit it just notes the code and raises (when
  stop-on-error).
- **`stdin=DEVNULL`.** The generated commands are non-interactive (`apt-get -y`, …); closing stdin turns any
  stray read into immediate EOF instead of a hang.
- **Return a `CompletedProcess`.** Keeps `apply_commands`'s error handling identical (`returncode` check) and
  makes the function a drop-in.

`run()` is deliberately left capturing (not streaming): it backs existence/discovery/listing probes whose
output is parsed, not displayed, and which are fast.

## Testing

`tests/test_system.py` exercises `run_streaming` against a real `bash -lc`: output capture + zero code, stderr
merged into stdout, non-zero code propagation, and stdin-closed (a bare `cat` returns instead of hanging). The
class is skipped unless `bash -lc "exit 0"` returns 0, so it runs on CI (Ubuntu) but skips hosts where `bash`
routes through a broken shim (e.g. Git-for-Windows' WSL relay).

## Constraint honored

No third-party dependency is introduced; `pyproject.toml` keeps `dependencies = []`. Streaming is implemented
entirely with the standard-library `subprocess` module.
