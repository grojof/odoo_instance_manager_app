#!/usr/bin/env python3
"""Execute what the data operations generate, instead of reading it.

The unit tests check the text of the plans; this runs it. The scheduled-backup
script, the retention prune and the "keep the data dir" step run against stub
binaries in a temp directory. The template copy, the forced drop, the owner probe
and the purge's database discovery run against a PostgreSQL cluster of our own
(its own data directory, port and socket; ``initdb`` refuses root, so this is a
developer-machine tool). Nothing touches the host's services or databases.

Run from the repository root: ``python3 tools/verify_data_safety.py``. Exits 1 when
any check fails.
"""

from __future__ import annotations

import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instance_manager import planners, system  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402
from instance_manager.workflows import backup_restore, common, purge  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def _write_exe(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _stub_bin(root: Path) -> Path:
    """`sudo -u <user>` runs the rest as us; pg_dump/pg_restore are scripted by env."""
    bindir = root / "stubs"
    bindir.mkdir()
    _write_exe(bindir / "sudo", 'if [ "$1" = "-u" ]; then shift 2; fi\nexec "$@"\n')
    _write_exe(
        bindir / "pg_dump",
        'case "${STUB_PG_DUMP:-ok}" in\n'
        "  ok) printf 'PGDMP fake dump\\n' ;;\n"
        "  empty) ;;\n"
        "  *) echo 'pg_dump: error: connection failed' >&2; exit 1 ;;\n"
        "esac\n",
    )
    _write_exe(
        bindir / "pg_restore",
        'file="${@: -1}"\n'
        'if [ "$1" = "--list" ] && head -c 5 "$file" 2>/dev/null | grep -q PGDMP; then exit 0; fi\n'
        "exit 1\n",
    )
    return bindir


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def _script(backup_dir: Path, filestore: Path, keep: int, include_filestore: bool = True) -> str:
    config = InstanceConfig(instance="shop")
    return planners._scheduled_backup_script(
        config, "acme", str(backup_dir), str(filestore), keep, include_filestore
    )


def _scheduled_backup(root: Path) -> None:
    bindir = _stub_bin(root)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    filestore = root / "filestore" / "acme"
    filestore.mkdir(parents=True)
    (filestore / "ab").mkdir()
    (filestore / "ab" / "abcdef").write_text("attachment", encoding="utf-8")

    for mode, label in (("fail", "a failed pg_dump"), ("empty", "an empty dump")):
        backup_dir = root / f"bk-{mode}"
        result = _run(_script(backup_dir, filestore, 3), dict(env, STUB_PG_DUMP=mode))
        names = sorted(p.name for p in backup_dir.iterdir()) if backup_dir.exists() else []
        check(f"scheduled backup exits non-zero on {label}", result.returncode != 0, result.stderr)
        check(f"scheduled backup leaves no file after {label}", names == [], str(names))

    backup_dir = root / "bk"
    backup_dir.mkdir()
    old = {
        "shop--acme--20250101_000000.dump": 1,
        "shop--acme--20250102_000000.dump": 2,
        "shop--acme--20250103_000000.dump": 3,
        "shop--test--20250101_000000.dump": 1,  # another database of the instance
        "shop_eu--acme--20250101_000000.dump": 1,  # another instance with the same start
        "shop_eu_20250101_000000.dump": 1,  # another instance, old name format
        "notes.txt": 1,
    }
    for name, age in old.items():
        path = backup_dir / name
        path.write_text("PGDMP old", encoding="utf-8")
        stamp = time.time() - 86400 * (10 - age)
        os.utime(path, (stamp, stamp))
    result = _run(_script(backup_dir, filestore, 2), env)
    check("scheduled backup succeeds with a good dump", result.returncode == 0, result.stderr)
    names = sorted(p.name for p in backup_dir.iterdir())
    acme_dumps = [n for n in names if n.startswith("shop--acme--") and n.endswith(".dump")]
    check("retention keeps the 2 newest dumps of the database", len(acme_dumps) == 2, str(acme_dumps))
    check(
        "retention keeps the newest old dump and drops the oldest",
        "shop--acme--20250103_000000.dump" in acme_dumps and "shop--acme--20250101_000000.dump" not in names,
        str(names),
    )
    untouched = ["shop--test--20250101_000000.dump", "shop_eu--acme--20250101_000000.dump",
                 "shop_eu_20250101_000000.dump", "notes.txt"]
    check("retention never touches other databases or instances", all(n in names for n in untouched), str(names))
    check("a filestore archive is written", any(n.endswith(".filestore.tar.gz") for n in names), str(names))
    check("no partial file is left", not any(n.endswith(".partial") for n in names), str(names))
    mode = stat.S_IMODE(backup_dir.stat().st_mode)
    check("the backup directory is private (700)", mode == 0o700, oct(mode))
    new_dump = next(backup_dir / n for n in acme_dumps if n not in old)
    file_mode = stat.S_IMODE(new_dump.stat().st_mode)
    check("the dump is private (600)", file_mode == 0o600, oct(file_mode))

    result = _run(_script(root / "bk-nofs", root / "missing", 2), env)
    check("scheduled backup fails when the filestore is missing", result.returncode != 0, result.stdout)

    marker = root / "pwned"
    hostile = root / f"bk$(touch {marker})"
    result = _run(_script(hostile, filestore, 2, include_filestore=False), env)
    check("a hostile backup path is taken literally", not marker.exists() and hostile.is_dir(), result.stderr)


def _manual_retention(root: Path) -> None:
    backup_dir = root / "manual"
    backup_dir.mkdir()
    names = [
        "shop--acme--20250101_000000.dump", "shop--acme--20250102_000000.dump",
        "shop_20250101_000000.dump", "shop_20250102_000000.dump",
        "shop_eu_20250101_000000.dump", "shop2--acme--20250101_000000.dump",
    ]
    for age, name in enumerate(names):
        path = backup_dir / name
        path.write_text("x", encoding="utf-8")
        stamp = time.time() - 3600 * (len(names) - age)
        os.utime(path, (stamp, stamp))
    commands = planners.plan_backup_retention(InstanceConfig(instance="shop"), str(backup_dir), 1, ["acme"])
    failed = [c.description for c in commands if _run(c.command, dict(os.environ)).returncode != 0]
    check("manual retention commands succeed", not failed, str(failed))
    left = sorted(p.name for p in backup_dir.iterdir())
    expected = ["shop--acme--20250102_000000.dump", "shop2--acme--20250101_000000.dump",
                "shop_20250102_000000.dump", "shop_eu_20250101_000000.dump"]
    check("manual retention prunes per group and spares look-alikes", left == expected, str(left))


def _keep_data_dir(root: Path) -> None:
    opt = root / "opt"
    kept_root = root / "kept"
    with mock.patch.object(InstanceConfig, "base_instances_dir", str(opt)), mock.patch.object(
        common, "_kept_data_dir_path", lambda config, ts: str(kept_root / config.instance / f"kept-{ts}")
    ):
        config = InstanceConfig(instance="shop")
        data_dir = Path(config.odoo_home) / ".local/share/Odoo"
        (data_dir / "filestore" / "acme").mkdir(parents=True)
        (data_dir / "filestore" / "acme" / "file").write_text("attachment", encoding="utf-8")
        (Path(config.odoo_home) / "odoo").mkdir()
        commands = common._keep_data_dir_commands(config, str(data_dir), "20261008_000000")
        commands.append(system.Command("Remove instance home", f"rm -rf {common._quote(config.odoo_home)}"))
        failed = [c.description for c in commands if _run(c.command, dict(os.environ)).returncode != 0]
        kept = kept_root / "shop" / "kept-20261008_000000" / "filestore" / "acme" / "file"
        check("delete keeps the data dir when the home is removed", not failed and kept.is_file(), str(failed))
        check("the home itself is gone", not Path(config.odoo_home).exists())


# --- against a PostgreSQL of our own ------------------------------------------


def _postgres_bindir() -> Path | None:
    found = shutil.which("initdb")
    if found:
        return Path(found).parent
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"), reverse=True)
    return candidates[0].parent if candidates else None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Cluster:
    def __init__(self, root: Path, bindir: Path) -> None:
        self.root, self.bin, self.port = root, bindir, _free_port()
        self.data = root / "data"

    def start(self) -> None:
        subprocess.run([str(self.bin / "initdb"), "-D", str(self.data), "-U", "postgres",
                        "--auth=trust", "--no-sync"], check=True, capture_output=True)
        subprocess.run([str(self.bin / "pg_ctl"), "-D", str(self.data), "-w", "-l",
                        str(self.root / "pg.log"), "-o",
                        f"-p {self.port} -k {self.root} -c listen_addresses=''", "start"],
                       check=True, capture_output=True)

    def stop(self) -> None:
        subprocess.run([str(self.bin / "pg_ctl"), "-D", str(self.data), "-m", "immediate",
                        "-w", "stop"], capture_output=True)

    def env(self, stubs: Path) -> dict[str, str]:
        return dict(os.environ, PATH=f"{stubs}:{self.bin}:{os.environ['PATH']}",
                    PGHOST=str(self.root), PGPORT=str(self.port), PGUSER="postgres")

    def value(self, sql: str) -> str:
        return self.value_in("postgres", sql)

    def value_in(self, db: str, sql: str) -> str:
        result = subprocess.run([str(self.bin / "psql"), "-X", "-h", str(self.root), "-p",
                                 str(self.port), "-U", "postgres", "-d", db, "-tAc", sql],
                                capture_output=True, text=True)
        return result.stdout.strip()


def _against_a_server(root: Path) -> None:
    bindir = _postgres_bindir()
    if bindir is None:
        # In CI a skip would pass silently: there it is a failure.
        check("PostgreSQL binaries found (initdb)", not os.environ.get("CI"))
        print("skip  PostgreSQL binaries not found — the server-backed checks need initdb")
        return
    if os.geteuid() == 0:
        print("skip  running as root — initdb refuses, so the server-backed checks are skipped")
        return
    stubs = root / "pgstubs"
    stubs.mkdir()
    _write_exe(stubs / "sudo", 'if [ "$1" = "-u" ]; then shift 2; fi\nexec "$@"\n')
    cluster = Cluster(root, bindir)
    try:
        cluster.start()
        env = cluster.env(stubs)
        for sql in ("CREATE ROLE prod LOGIN", "CREATE ROLE dev LOGIN", "CREATE ROLE shop LOGIN",
                    "CREATE ROLE other LOGIN"):
            cluster.value(sql)
        for name, owner in (("prod", "prod"), ("shop", "postgres"), ("shop2", "other"),
                            ("shopXeu", "other"), ("shop_eu", "other"), ("shop_mine", "shop")):
            cluster.value(f'CREATE DATABASE "{name}" OWNER {owner}')

        with mock.patch.dict(os.environ, env):
            check("database_owner reads the owner", system.database_owner("prod") == "prod")
            check("database_owner of a missing database is None", system.database_owner("nope") is None)
            check("database_exists sees an existing database", system.database_exists("prod"))
            check(
                "an existing target of another role is refused",
                backup_restore._existing_target_error("prod", "dev") is not None,
            )

        session = subprocess.Popen([str(bindir / "psql"), "-X", "-h", str(root), "-p", str(cluster.port),
                                    "-U", "postgres", "-d", "prod", "-c", "SELECT pg_sleep(60)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        script = backup_restore._template_copy_script("prod", "prod_copy")
        result = _run(script, env)
        check("template copy succeeds with a live session on the source", result.returncode == 0, result.stderr)
        check("the copy exists, owned by postgres until it is handed over", cluster.value(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'prod_copy'") == "postgres")
        check("the source is open again", cluster.value(
            "SELECT datallowconn FROM pg_database WHERE datname = 'prod'") == "t")
        session.wait(timeout=10)

        result = _run(script, env)  # the target exists now: createdb fails
        check("a failed template copy exits non-zero", result.returncode != 0)
        check("the source is reopened after a failure", cluster.value(
            "SELECT datallowconn FROM pg_database WHERE datname = 'prod'") == "t")

        session = subprocess.Popen([str(bindir / "psql"), "-X", "-h", str(root), "-p", str(cluster.port),
                                    "-U", "postgres", "-d", "prod_copy", "-c", "SELECT pg_sleep(60)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        drop = backup_restore._drop_db_commands("prod_copy")
        results = [_run(c.command, env) for c in drop]
        check("the drop succeeds with a live session", all(r.returncode == 0 for r in results),
              " ".join(r.stderr for r in results))
        check("the database is gone", cluster.value(
            "SELECT count(*) FROM pg_database WHERE datname = 'prod_copy'") == "0")
        session.wait(timeout=10)

        found = cluster.value(purge._instance_databases_sql("shop", "shop")).split()
        check("purge selects the exact name and the role's databases", sorted(found) == ["shop", "shop_mine"],
              str(found))
        others = cluster.value(purge._prefix_only_databases_sql("shop_eu", "shop_eu")).split()
        check("the prefix report escapes '_' (no shopXeu)", others == [], str(others))
        others = cluster.value(purge._prefix_only_databases_sql("shop", "shop")).split()
        check("the prefix report lists look-alikes it did not select",
              sorted(others) == ["shop2", "shopXeu", "shop_eu"], str(others))
    finally:
        cluster.stop()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="oim-verify-data-") as tmp:
        root = Path(tmp)
        for part in ("sched", "manual", "keep", "pg"):
            (root / part).mkdir()
        _scheduled_backup(root / "sched")
        _manual_retention(root / "manual")
        _keep_data_dir(root / "keep")
        _against_a_server(root / "pg")
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
