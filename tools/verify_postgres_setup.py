#!/usr/bin/env python3
"""Run the PostgreSQL steps of an install against a cluster of our own.

The cluster listens on a port that is not 5432 and ``PGPORT`` is unset, so every
step must name the instance's port. It stores passwords as md5 by default, as
PostgreSQL 13 does. Then, with ``systemctl`` stubbed onto ``pg_ctl``:

- the version floor check passes;
- the role is created with a scram password (the pg_hba rule asks for scram);
- ``listen_addresses`` is set to ``*`` with ``ALTER SYSTEM`` — which also wins over a
  ``conf.d`` file — and PostgreSQL restarted once; a second run restarts nothing;
- the pg_hba rule is added once, and PostgreSQL reloaded, not restarted.

``initdb`` refuses root, so this is a developer-machine (and CI) tool.

    python3 tools/verify_postgres_setup.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from verify_data_safety import Cluster, _postgres_bindir, _write_exe  # noqa: E402

from instance_manager import planners  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail[-400:]}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def main() -> int:
    bindir = _postgres_bindir()
    if bindir is None or os.geteuid() == 0:
        check("initdb and a non-root user are available", not os.environ.get("CI"))
        print("skip  needs initdb and a non-root user")
        return 1 if FAILURES else 0
    with tempfile.TemporaryDirectory(prefix="oim-verify-pg-") as tmp:
        root = Path(tmp)
        stubs = root / "stubs"
        stubs.mkdir()
        cluster = Cluster(root, bindir)
        calls = root / "calls"
        _write_exe(stubs / "sudo", 'while [ "${1#-}" != "$1" ]; do if [ "$1" = "-u" ]; then shift; fi; shift; done\n'
                                   'exec "$@"\n')
        pg_ctl = f"{bindir}/pg_ctl -D {cluster.data} -w -l {root}/pg.log"
        # A restart without the start's listen_addresses='' override, so the
        # setting the step makes takes effect.
        _write_exe(stubs / "systemctl", f'echo "systemctl $*" >> {calls}\n'
                                        f'case "$1" in restart) {pg_ctl} -o "-p {cluster.port} -k {root}" restart '
                                        '>/dev/null;; reload) ' + f"{bindir}/pg_ctl -D {cluster.data} reload >/dev/null;; esac\n")
        try:
            cluster.start()
            cluster.value("ALTER SYSTEM SET password_encryption = 'md5'")
            cluster.value("SELECT pg_reload_conf()")
            # A distribution's conf.d setting, which a sed on postgresql.conf would miss.
            (cluster.data / "conf.d").mkdir()
            (cluster.data / "conf.d" / "listen.conf").write_text("listen_addresses = 'localhost'\n", encoding="utf-8")
            with open(cluster.data / "postgresql.conf", "a", encoding="utf-8") as conf:
                conf.write("include_dir = 'conf.d'\n")
            env = cluster.env(stubs)
            env.pop("PGPORT")
            env["PGHOST"] = str(root)

            config = InstanceConfig(instance="shop", db_port=cluster.port, app_server_ip="127.0.0.2")
            config.db_password = "S3cret-pg-setup"
            config.odoo_admin_passwd = "x"
            steps = [c for c in planners.plan_db_setup(config, ensure_remote_access=True)
                     if not c.description.startswith(("Install PostgreSQL", "Enable and start", "Validate DB user"))]
            for command in steps:
                result = subprocess.run(["bash", "-c", command.command], capture_output=True, text=True,
                                        env={**env, **command.env})
                check(f"step runs: {command.description}", result.returncode == 0, result.stderr + result.stdout)

            check("the role's password is stored as scram",
                  cluster.value("SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname = 'shop'") == "t")
            check("PostgreSQL listens on every address", cluster.value("SHOW listen_addresses") == "*")
            log = calls.read_text(encoding="utf-8").split("\n") if calls.exists() else []
            check("restarted once, for listen_addresses", log.count("systemctl restart postgresql") == 1, str(log))
            check("reloaded for pg_hba", "systemctl reload postgresql" in log, str(log))

            calls.unlink()
            for command in steps:
                subprocess.run(["bash", "-c", command.command], capture_output=True, text=True,
                               env={**env, **command.env})
            log = calls.read_text(encoding="utf-8").split("\n") if calls.exists() else []
            check("a second run restarts nothing", "systemctl restart postgresql" not in log, str(log))
            # An existing role: kept as it is, or given the new password on request.
            def stored() -> str:
                return cluster.value("SELECT rolpassword FROM pg_authid WHERE rolname = 'shop'")

            before = stored()
            config.db_password = "S3cret-pg-setup-new"
            for reset, label in ((False, "kept without reset"), (True, "replaced on reset")):
                step = next(c for c in planners.plan_db_setup(config, ensure_remote_access=False, reset_password=reset)
                            if c.description.startswith("Ensure PostgreSQL role"))
                result = subprocess.run(["bash", "-c", step.command], capture_output=True, text=True,
                                        env={**env, **step.env})
                changed = stored() != before
                check(f"an existing role's password is {label}", result.returncode == 0 and changed == reset,
                      result.stderr)
            check("and stored as scram", stored().startswith("SCRAM-SHA-256$"))
            hba = (cluster.data / "pg_hba.conf").read_text(encoding="utf-8")
            check("the pg_hba rule is there once",
                  hba.count("host    all     shop     127.0.0.2/32     scram-sha-256") == 1, hba[-300:])
        finally:
            cluster.stop()
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
