#!/usr/bin/env python3
"""Check, by running them, that plan steps keep secrets out of sight.

- a step's password, passed through ``Command.env``, is not in any process's
  arguments while it runs (``ps`` shows every user's), while the old form —
  ``PGPASSWORD=…`` in the command text — is (negative control);
- ``write_text_file_command`` writes the exact content with the asked mode, leaves
  no temporary file, and its preview masks the secrets;
- a failed step's error names the step, not its command;
- the role SQL sent on stdin creates a role with that password, against a
  PostgreSQL cluster of our own (skipped without ``initdb`` or as root).

    python3 tools/verify_secrets.py
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from verify_data_safety import Cluster, _postgres_bindir, _write_exe  # noqa: E402

from instance_manager import planners, system  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402

FAILURES: list[str] = []
SECRET = "S3cr3t-oim-check-7f1c"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail[-400:]}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def _seen_in_ps(start, needle: str) -> bool:
    """Start something, then look for ``needle`` in every process's arguments."""
    seen = []
    thread = threading.Thread(target=start)
    thread.start()
    for _ in range(20):
        time.sleep(0.1)
        seen.append(needle in subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout)
    thread.join()
    return any(seen)


def _argv() -> None:
    step = system.Command("wait", 'sleep 1.5; test -n "$PGPASSWORD"', env=system.pg_env(SECRET))
    check("a password in the step's environment is not in any process's arguments",
          not _seen_in_ps(lambda: system.run(step.command, env=step.env), SECRET))
    old = f"PGPASSWORD={SECRET} sleep 1.5 && true"
    check("negative control: PGPASSWORD in the command text is visible in ps",
          _seen_in_ps(lambda: system.run(old), SECRET))
    result = system.run(step.command, env=step.env)
    check("the step still receives the password", result.returncode == 0, result.stderr)


def _files(root: Path) -> None:
    config = InstanceConfig(instance="shop")
    config.db_password, config.odoo_admin_passwd = SECRET, SECRET + "-master"
    content = planners._odoo_conf_content(config)
    target = root / "shop.conf"
    [command] = planners.write_text_file_command(str(target), content, "640",
                                                 secrets=(config.db_password, config.odoo_admin_passwd))
    check("the file content is not in the command text", SECRET not in command.command)
    check("the preview shows the file with its secrets masked",
          SECRET not in command.shown and "db_password = ********" in command.shown, command.shown)
    result = system.run(command.command, env=command.env)
    check("the file is written exactly", result.returncode == 0 and target.read_text() == content, result.stderr)
    check("with the asked mode", stat.S_IMODE(target.stat().st_mode) == 0o640, oct(target.stat().st_mode))
    check("leaving no temporary file", [p.name for p in root.iterdir()] == ["shop.conf"],
          str(list(root.iterdir())))


def _errors() -> None:
    step = system.Command("Do the secret thing", f"false {SECRET}", display="false ********")
    try:
        system.apply_commands([step])
        message = ""
    except RuntimeError as error:
        message = str(error)
    check("a failed step's error names the step, not its command",
          "Do the secret thing" in message and SECRET not in message, message)


def _role(root: Path) -> None:
    bindir = _postgres_bindir()
    if bindir is None or os.geteuid() == 0:
        check("initdb and a non-root user are available", not os.environ.get("CI"))
        print("skip  the role check needs initdb and a non-root user")
        return
    stubs = root / "stubs"
    stubs.mkdir()
    _write_exe(stubs / "sudo", 'while [ "${1#-}" != "$1" ]; do if [ "$1" = "-u" ]; then shift; fi; shift; done\nexec "$@"\n')
    cluster = Cluster(root / "pg", bindir)
    (root / "pg").mkdir()
    try:
        cluster.start()
        # PostgreSQL 13's default: the role SQL must still store a scram password.
        cluster.value("ALTER SYSTEM SET password_encryption = 'md5'")
        cluster.value("SELECT pg_reload_conf()")
        # The step names the instance's port; PGPORT alone would not reach it.
        config = InstanceConfig(instance="shop", db_port=cluster.port)
        config.db_password, config.odoo_admin_passwd = SECRET, "x"
        step = next(c for c in planners.plan_ensure_db_role(config) if "OIM_SQL" in c.command)
        check("the role SQL is not in the command text", SECRET not in step.command and SECRET not in step.shown)
        result = subprocess.run(["bash", "-c", step.command], capture_output=True, text=True,
                                env={**cluster.env(stubs), **step.env})
        check("the role is created through stdin", result.returncode == 0, result.stderr)
        check("with a password set",
              cluster.value("SELECT rolpassword IS NOT NULL FROM pg_authid WHERE rolname = 'shop'") == "t")
        check("stored as scram even where the server defaults to md5 (PostgreSQL 13)",
              cluster.value("SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname = 'shop'") == "t",
              cluster.value("SELECT left(rolpassword, 14) FROM pg_authid WHERE rolname = 'shop'"))
    finally:
        cluster.stop()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="oim-verify-secrets-") as tmp:
        root = Path(tmp)
        (root / "files").mkdir()
        _argv()
        _files(root / "files")
        _errors()
        _role(root)
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
