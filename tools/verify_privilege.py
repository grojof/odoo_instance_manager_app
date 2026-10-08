#!/usr/bin/env python3
"""Run what reaches a root shell or a superuser session, instead of reading it.

- the certificate step with real ``openssl``: a matching pair is installed (the
  previous files kept as ``.previous``), a key that does not match leaves the live
  files as they were, a hostile file name is taken literally, a chain is joined;
- the self-signed step with real ``openssl``;
- the wkhtmltopdf step with stub ``curl``/``apt-get``: a wrong SHA-256 installs
  nothing, a right one installs from a private directory that is gone afterwards;
- the replica's venv replication with stub ``pip``s: only ``name==version`` lines
  reach the target, and a failing install fails the step;
- neutralisation as the copy's owner, against a PostgreSQL of our own: a trigger the
  source database carries cannot raise its owner to superuser, while the same step
  run as the superuser lets it (negative control).

Nothing touches the host's services or databases (``initdb`` refuses root, so the
server-backed check is a developer-machine one).

    python3 tools/verify_privilege.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from verify_data_safety import Cluster, _postgres_bindir, _rebase, _write_exe  # noqa: E402

from instance_manager import planners  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402
from instance_manager.workflows import backup_restore  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail[-400:]}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def _stub_env(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Each named command records its arguments and succeeds."""
    bindir = root / "stubs"
    bindir.mkdir(exist_ok=True)
    for name in names:
        _write_exe(bindir / name, f'echo "{name} $*" >> {root}/calls\n')
    _write_exe(bindir / "sudo", 'while [ "${1#-}" != "$1" ]; do if [ "$1" = "-u" ]; then shift; fi; shift; done\n'
                                'exec "$@"\n')
    return dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")


def _local(command: str, root: Path) -> str:
    """A cert step runnable without root: host paths under ``root``, and the
    directory made without a root owner (chown itself is a stub)."""
    return _rebase(command, root).replace("install -d -m 750 -o root -g www-data", "install -d -m 750")


def _openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def _pair(directory: Path, name: str) -> tuple[Path, Path]:
    key, cert = directory / f"{name}.key", directory / f"{name}.crt"
    _openssl("req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "2", "-subj", f"/CN={name}",
             "-keyout", str(key), "-out", str(cert))
    return key, cert


def _certificates(root: Path) -> None:
    if shutil.which("openssl") is None:
        check("openssl found", not os.environ.get("CI"))
        print("skip  openssl not found")
        return
    env = _stub_env(root, ("chown",))
    src = root / "src"
    src.mkdir()
    key, cert = _pair(src, "one")
    other_key = _pair(src, "two")[0]
    ca = _pair(src, "ca")[1]
    config = InstanceConfig(instance="shop", domain="erp.example.com")
    live_cert = Path(_rebase(config.ssl_cert_file, root))

    [step] = planners.plan_copy_custom_certs(config, str(cert), str(key), None)
    result = _run(_local(step.command, root), env)
    check("a matching pair is installed", result.returncode == 0 and live_cert.read_bytes() == cert.read_bytes(),
          result.stderr)
    check("the key is installed private (640)", oct(Path(_rebase(config.ssl_key_file, root)).stat().st_mode & 0o777)
          == "0o640")
    check("no staging directory is left", not list(live_cert.parent.glob(".stage.*")))

    before = {p.name: p.read_bytes() for p in live_cert.parent.iterdir()}
    [step] = planners.plan_copy_custom_certs(config, str(cert), str(other_key), None)
    result = _run(_local(step.command, root), env)
    after = {p.name: p.read_bytes() for p in live_cert.parent.iterdir()}
    check("a key that does not match fails the step", result.returncode != 0)
    check("and leaves the live files as they were", before == after, str(sorted(after)))

    hostile = src / "x$(touch PWNED)'y.crt"
    shutil.copy(cert, hostile)
    [step] = planners.plan_copy_custom_certs(config, str(hostile), str(key), str(ca))
    result = subprocess.run(["bash", "-c", _local(step.command, root)], capture_output=True, text=True, env=env,
                            cwd=root)
    check("a hostile file name is taken literally", not (root / "PWNED").exists(), result.stderr)
    check("the step still runs", result.returncode == 0, result.stderr)
    chain = Path(_rebase(config.ssl_fullchain_file, root)).read_text(encoding="utf-8")
    check("the full chain holds the certificate then the intermediate", chain.count("BEGIN CERTIFICATE") == 2)
    check("the previous files are kept", Path(_rebase(config.ssl_cert_file + ".previous", root)).is_file())

    self_signed = InstanceConfig(instance="self", domain="self.example.com")
    failed = [c.description for c in planners.plan_ensure_self_signed_certs(self_signed)
              if _run(_local(c.command, root), env).returncode != 0]
    check("the self-signed steps run", not failed, str(failed))
    check("they leave a key and a full chain",
          Path(_rebase(self_signed.ssl_key_file, root)).is_file()
          and Path(_rebase(self_signed.ssl_fullchain_file, root)).is_file())


def _wkhtmltopdf(root: Path) -> None:
    payload = b"fake deb"
    calls = root / "calls"
    env = _stub_env(root, ("apt-get",))
    _write_exe(root / "stubs" / "curl", 'while [ "$1" != "-o" ]; do shift; done\nprintf "fake deb" > "$2"\n')
    for digest, should_install in (("0" * 64, False), (hashlib.sha256(payload).hexdigest(), True)):
        calls.unlink(missing_ok=True)
        planners_asset = ("https://example.invalid/w.deb", "w.deb", digest)
        original = planners.resolve_wkhtmltopdf_asset
        planners.resolve_wkhtmltopdf_asset = lambda codename, asset=planners_asset: asset
        try:
            step = planners.plan_install_wkhtmltopdf("patched", "noble")[-1]
        finally:
            planners.resolve_wkhtmltopdf_asset = original
        result = _run(step.command, env)
        installed = calls.exists() and "install " in calls.read_text(encoding="utf-8")
        label = "a matching SHA-256 installs" if should_install else "a wrong SHA-256 installs nothing"
        check(label, installed == should_install and (result.returncode == 0) == should_install,
              (calls.read_text(encoding="utf-8") if calls.exists() else "") + result.stderr)
        if should_install:
            deb = calls.read_text(encoding="utf-8").split()[-1]
            check("from a private directory that is gone afterwards", not deb.startswith("/tmp/w")
                  and not Path(deb).exists(), deb)


def _venv_replication(root: Path) -> None:
    opt = root / "opt"
    env = _stub_env(root, ())
    source, target = InstanceConfig(instance="prod"), InstanceConfig(instance="dev")
    freeze = "Babel==2.14.0\n-e git+https://example.invalid/x.git#egg=x\nevil @ file:///tmp/evil\nlxml==5.2.1\n"
    for config in (source, target):
        (opt / config.instance / "venv" / "bin").mkdir(parents=True)
    _write_exe(opt / "prod/venv/bin/pip", f"cat <<'EOF'\n{freeze}EOF\n")
    received = root / "received"
    for target_exit, label in ((0, "succeeds"), (1, "fails")):
        _write_exe(opt / "dev/venv/bin/pip", f'cat > {received}\nexit {target_exit}\n')
        command = backup_restore._replicate_venv_packages_command(source, target).command
        result = _run(command.replace("/opt/odoo", str(opt)), env)
        if target_exit == 0:
            got = received.read_text(encoding="utf-8").split()
            check("only name==version lines reach the target", got == ["Babel==2.14.0", "lxml==5.2.1"], str(got))
            check("the replication succeeds", result.returncode == 0, result.stderr)
        else:
            check(f"a target install that {label} fails the step", result.returncode != 0, result.stdout)


def _neutralise_as_owner(root: Path) -> None:
    bindir = _postgres_bindir()
    if bindir is None or os.geteuid() == 0:
        check("initdb and a non-root user are available", not os.environ.get("CI"))
        print("skip  the neutralisation check needs initdb and a non-root user")
        return
    stubs = root / "pgstubs"
    stubs.mkdir()
    _write_exe(stubs / "sudo", 'while [ "${1#-}" != "$1" ]; do if [ "$1" = "-u" ]; then shift; fi; shift; done\n'
                               'exec "$@"\n')
    (root / "pg").mkdir()
    cluster = Cluster(root / "pg", bindir)
    try:
        cluster.start()
        env = cluster.env(stubs)
        cluster.value("CREATE ROLE dev LOGIN")
        for db in ("copy_owner", "copy_superuser"):
            cluster.value(f'CREATE DATABASE "{db}"')
            for sql in (
                "CREATE TABLE ir_config_parameter (id serial PRIMARY KEY, key varchar UNIQUE NOT NULL, value text, "
                "create_uid int, create_date timestamp, write_uid int, write_date timestamp)",
                "ALTER TABLE ir_config_parameter OWNER TO dev",
                # What a hostile source database could carry: a trigger raising its owner.
                "CREATE FUNCTION escalate() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN EXECUTE 'ALTER ROLE dev SUPERUSER'; RETURN NEW; END $$",
                "ALTER FUNCTION escalate() OWNER TO dev",
                "CREATE TRIGGER escalate BEFORE INSERT OR UPDATE ON ir_config_parameter "
                "FOR EACH ROW EXECUTE FUNCTION escalate()",
            ):
                cluster.value_in(db, sql)

        [step] = backup_restore._post_db_mode_commands(
            backup_restore._psql_target_local("copy_owner"), 'Copied (new UUID on target)', False,
            "http://127.0.0.1:8069", role="dev",
        )
        result = _run(step.command, env)
        superuser = cluster.value("SELECT rolsuper FROM pg_roles WHERE rolname = 'dev'")
        check("run as the owner, the trigger cannot raise its role", superuser == "f", result.stderr)
        check("and the step fails instead of going on", result.returncode != 0)

        [step] = backup_restore._post_db_mode_commands(
            backup_restore._psql_target_local("copy_superuser"), 'Copied (new UUID on target)', False,
            "http://127.0.0.1:8069",
        )
        _run(step.command, env)
        superuser = cluster.value("SELECT rolsuper FROM pg_roles WHERE rolname = 'dev'")
        check("negative control: run as the superuser, the trigger raises it", superuser == "t")
        cluster.value("ALTER ROLE dev NOSUPERUSER")

        # As the owner, the rules still find the tables: the copy is really neutralised.
        cluster.value('CREATE DATABASE "copy_plain"')
        for sql in (
            "CREATE TABLE ir_config_parameter (id serial PRIMARY KEY, key varchar UNIQUE NOT NULL, value text)",
            "CREATE TABLE ir_cron (id serial PRIMARY KEY, active boolean, cron_name varchar)",
            "CREATE TABLE ir_model_data (id serial PRIMARY KEY, module varchar, name varchar, model varchar, "
            "res_id int)",
            "INSERT INTO ir_config_parameter (key, value) VALUES ('web.base.url', 'https://erp.example.com')",
            "INSERT INTO ir_cron (active, cron_name) VALUES (true, 'send invoices')",
            "ALTER TABLE ir_config_parameter OWNER TO dev",
            "ALTER TABLE ir_cron OWNER TO dev",
            "ALTER TABLE ir_model_data OWNER TO dev",
        ):
            cluster.value_in("copy_plain", sql)
        steps = backup_restore._post_db_mode_commands(
            backup_restore._psql_target_local("copy_plain"), "Moved (keep UUID)", True,
            "http://127.0.0.1:8069", role="dev",
        )
        results = [_run(c.command, env) for c in steps]
        check("as the owner, the neutralisation and its check run",
              all(r.returncode == 0 for r in results), " ".join(r.stderr for r in results))
        check("and reach the tables (base URL and crons changed)",
              cluster.value_in("copy_plain", "SELECT value FROM ir_config_parameter WHERE key = 'web.base.url'")
              == "http://127.0.0.1:8069"
              and cluster.value_in("copy_plain", "SELECT count(*) FROM ir_cron WHERE active") == "0")

        cluster.value('CREATE DATABASE "not_odoo"')
        check_step = backup_restore._post_db_mode_commands(
            backup_restore._psql_target_local("not_odoo"), "Moved (keep UUID)", True,
            "http://127.0.0.1:8069", role="dev",
        )[-1]
        result = _run(check_step.command, env)
        check("the check fails where it sees no Odoo table, instead of passing on nothing",
              result.returncode != 0 and "no Odoo tables" in result.stderr, result.stderr)
        _staged_copies(cluster, env)
    finally:
        cluster.stop()


def _staged_copy(source: str, target: str) -> str:
    reader = InstanceConfig(instance="dev")
    return backup_restore._local_copy_command(
        "copy", target, "dev", backup_restore._seed_db_commands(source, target, "dev", "dump"),
        "Moved (keep UUID)", False, "http://127.0.0.1:8069", reader,
    ).command


def _staged_copies(cluster: Cluster, env: dict[str, str]) -> None:
    """The copy is one step: done whole, or its database is dropped."""
    def exists(db: str) -> bool:
        return cluster.value(f"SELECT count(*) FROM pg_database WHERE datname = '{db}'") == "1"

    result = _run(_staged_copy("copy_plain", "staged_ok"), env)
    check("a staged copy succeeds", result.returncode == 0, result.stderr)
    state = cluster.value("SELECT pg_get_userbyid(datdba) || ' ' || has_database_privilege('dev', 'staged_ok', "
                          "'CONNECT') || ' ' || coalesce(shobj_description(oid, 'pg_database'), '-') "
                          "FROM pg_database WHERE datname = 'staged_ok'")
    check("and is handed over: owned by its role, connectable, unmarked", state == "dev true -", state)

    result = _run(_staged_copy("no_such_source", "staged_fail"), env)
    check("a copy that fails partway fails the step", result.returncode != 0)
    check("and leaves no unfinished database behind", not exists("staged_fail"), result.stderr)

    cluster.value('CREATE DATABASE "already_there"')
    result = _run(_staged_copy("copy_plain", "already_there"), env)
    check("a target that already exists is never dropped by the copy",
          result.returncode != 0 and exists("already_there"), result.stderr)

    cluster.value('CREATE DATABASE "left_over"')
    cluster.value(f"COMMENT ON DATABASE \"left_over\" IS '{backup_restore.STAGING_COMMENT}'")
    with mock.patch.dict(os.environ, env):
        check("an interrupted run's copy is recognised as its own", backup_restore._is_staging_leftover("left_over")
              and backup_restore._existing_target_error("left_over", "dev") is None)
        check("a database merely owned by postgres is not",
              not backup_restore._is_staging_leftover("already_there")
              and backup_restore._existing_target_error("already_there", "dev") is not None)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="oim-verify-privilege-") as tmp:
        root = Path(tmp)
        for part in ("certs", "wk", "venv", "pg"):
            (root / part).mkdir()
        _certificates(root / "certs")
        _wkhtmltopdf(root / "wk")
        _venv_replication(root / "venv")
        _neutralise_as_owner(root / "pg")
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
