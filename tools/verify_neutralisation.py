#!/usr/bin/env python3
"""Neutralise a real Odoo database with the commands a duplication generates.

For each Odoo given (an interpreter and a checkout), in a PostgreSQL cluster of our
own: install base, mail, payment, delivery, OAuth and IAP into a source database,
arm it as production is armed (active crons, a mail server with credentials, an
enabled payment provider, carriers in production, a production base URL), then
run the duplication plan's own commands — seed (pg_dump copy), copied identity,
neutralisation, guard, hand-over — and check:

- the guard refuses the armed source and accepts the copy;
- the copy is invisible to the target role until it is handed over (Odoo's
  ``list_dbs`` lists only the databases the connected role owns);
- Odoo itself, on the copy, cannot send a mail (the sink, not odoo.conf's server);
- the copy has its own ``database.uuid`` and ``database.secret``.

Nothing touches the host's cluster or the checkouts (``PYTHONDONTWRITEBYTECODE``).

    python3 tools/verify_neutralisation.py --odoo 18=/path/venv/bin/python:/path/odoo-18.0
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from verify_data_safety import Cluster, _postgres_bindir, _write_exe  # noqa: E402

from instance_manager.models import InstanceConfig  # noqa: E402
from instance_manager.workflows import backup_restore  # noqa: E402

FAILURES: list[str] = []
URL = "http://127.0.0.1:8070"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail[-600:]}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def _odoo(python: str, clone: Path, cluster: Cluster, data: Path, db: str, *args: str,
          stdin: str | None = None, role: str = "shop") -> subprocess.CompletedProcess[str]:
    cmd = [python, str(clone / "odoo-bin"), *args, "-d", db, "-r", role, "--db_host", str(cluster.root),
           "--db_port", str(cluster.port), "--data-dir", str(data),
           "--addons-path", f"{clone}/addons,{clone}/odoo/addons"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(cmd, capture_output=True, text=True, input=stdin, env=env)


def _arm(cluster: Cluster, db: str, major: int) -> None:
    psql = [str(cluster.bin / "psql"), "-X", "-q", "-h", str(cluster.root), "-p", str(cluster.port),
            "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-c"]
    auth = ", smtp_authentication" if major >= 15 else ""
    auth_value = ", 'login'" if major >= 15 else ""
    statements = [
        "UPDATE ir_cron SET active = true",
        "INSERT INTO ir_mail_server (name, smtp_host, smtp_port, smtp_encryption, smtp_user, smtp_pass, "
        f"sequence, active{auth}) VALUES ('production relay', 'smtp.example.com', 587, 'starttls', "
        f"'prod@example.com', 's3cret', 5, true{auth_value})",
        "UPDATE ir_config_parameter SET value = 'https://erp.example.com' WHERE key = 'web.base.url'",
        "UPDATE delivery_carrier SET prod_environment = true",
        "UPDATE auth_oauth_provider SET enabled = true",
    ]
    if major >= 17:
        statements.append("INSERT INTO ir_config_parameter (key, value) VALUES "
                          "('mail.web_push_vapid_private_key', 'production-push-key')")
    else:
        # Installed as 'demo'; production sets 'prod' (or removes it).
        statements.append("UPDATE ir_config_parameter SET value = 'prod' "
                          "WHERE key = 'account_edi_proxy_client.demo'")
    if major >= 16:
        statements.append("UPDATE payment_provider SET state = 'enabled' WHERE code = 'demo' OR id = "
                          "(SELECT min(id) FROM payment_provider)")
    else:
        statements.append("UPDATE payment_acquirer SET state = 'enabled' WHERE id = "
                          "(SELECT min(id) FROM payment_acquirer)")
    for sql in statements:
        result = subprocess.run([*psql, sql], capture_output=True, text=True)
        check(f"arm the source: {sql[:48]}…", result.returncode == 0, result.stderr)


def _visible_to(cluster: Cluster, role: str, db: str) -> bool:
    """Odoo's own list_dbs query, run as ``role``."""
    sql = ("select datname from pg_database where datdba=(select usesysid from pg_user where "
           "usename=current_user) and not datistemplate and datallowconn")
    result = subprocess.run([str(cluster.bin / "psql"), "-X", "-tA", "-h", str(cluster.root), "-p",
                             str(cluster.port), "-U", role, "-d", "postgres", "-c", sql],
                            capture_output=True, text=True)
    return db in result.stdout.split()


def _one(major: int, python: str, clone: Path, cluster: Cluster, env: dict[str, str], root: Path) -> None:
    src, dst = f"prod{major}", f"copy{major}"
    data = root / f"data{major}"
    modules = ("base,mail,payment,delivery,auth_oauth,iap,account_edi_proxy_client"
               + (",fetchmail" if major <= 16 else ""))
    print(f"info  Odoo {major}: installing {modules} (a few minutes)", flush=True)
    result = _odoo(python, clone, cluster, data, src, "-i", modules, "--without-demo=all",
                   "--stop-after-init", "--no-http")
    check(f"Odoo {major}: source database installed", result.returncode == 0, result.stderr)
    if result.returncode != 0:
        return
    _arm(cluster, src, major)

    guard = backup_restore._post_db_mode_commands(
        backup_restore._psql_target_local(src), "Moved (keep UUID)", True, URL)[-1]
    result = subprocess.run(["bash", "-c", guard.command], capture_output=True, text=True, env=env)
    check(f"Odoo {major}: the guard refuses the armed source",
          result.returncode != 0 and "can still act on the outside" in result.stderr, result.stderr)

    # Odoo's own neutralize.sql is read from this checkout, as the copy's reader.
    reader = InstanceConfig(instance="dev")
    backup_restore._addons_paths = lambda config: [f"{clone}/odoo/addons", f"{clone}/addons"]
    plan = (backup_restore._seed_db_commands(src, dst, "dev", "dump")
            + backup_restore._post_db_mode_commands(
                backup_restore._psql_target_local(dst), "Copied (new UUID on target)", True, URL, role="dev",
                odoo_sql_reader=reader))
    for command in plan:
        result = subprocess.run(["bash", "-c", command.command], capture_output=True, text=True, env=env)
        output = result.stdout + result.stderr
        first_error = next((line for line in output.splitlines() if "ERROR" in line), output)
        check(f"Odoo {major}: {command.description}", result.returncode == 0, first_error)
        if result.returncode != 0:
            return
    check(f"Odoo {major}: the copy is invisible to its role before the hand-over",
          not _visible_to(cluster, "dev", dst))
    for command in backup_restore._hand_over_commands(dst, "dev"):
        result = subprocess.run(["bash", "-c", command.command], capture_output=True, text=True, env=env)
        check(f"Odoo {major}: {command.description}", result.returncode == 0, result.stderr)
    check(f"Odoo {major}: the copy is visible to its role after the hand-over", _visible_to(cluster, "dev", dst))

    again = backup_restore._post_db_mode_commands(
        backup_restore._psql_target_local(dst), "Moved (keep UUID)", True, URL, role="dev")
    results = [subprocess.run(["bash", "-c", c.command], capture_output=True, text=True, env=env) for c in again]
    check(f"Odoo {major}: neutralising again is harmless", all(r.returncode == 0 for r in results),
          " ".join(r.stderr for r in results))

    def value(db: str, sql: str) -> str:
        return cluster.value_in(db, sql)

    for key in ("database.uuid", "database.secret"):
        q = f"SELECT value FROM ir_config_parameter WHERE key = '{key}'"
        check(f"Odoo {major}: the copy has its own {key}", value(src, q) != value(dst, q) and value(dst, q) != "")
    check(f"Odoo {major}: the source is untouched (crons still active)",
          value(src, "SELECT count(*) FROM ir_cron WHERE NOT active") == "0")
    check(f"Odoo {major}: production's mail password is gone from the copy",
          value(dst, "SELECT count(*) FROM ir_mail_server WHERE smtp_pass IS NOT NULL") == "0")
    check(f"Odoo {major}: the copy's base URL is local",
          value(dst, "SELECT value FROM ir_config_parameter WHERE key = 'web.base.url'") == URL)
    if major >= 16:
        check(f"Odoo {major}: Odoo's own neutralize.sql ran (its mail sink is there)",
              value(dst, "SELECT count(*) FROM ir_mail_server WHERE name = 'neutralization - disable emails'") != "0")
    if major <= 16:
        check(f"Odoo {major}: the EDI proxy is in demo mode",
              value(dst, "SELECT value FROM ir_config_parameter WHERE key = 'account_edi_proxy_client.demo'")
              not in {"", "prod"},
              value(dst, "SELECT coalesce(to_regclass('account_edi_proxy_client_user')::text, 'no table') || ' / ' "
                         "|| (SELECT string_agg(name || ':' || state, ',') FROM ir_module_module "
                         "WHERE name LIKE 'account_edi%')"))
    if major >= 17:
        check(f"Odoo {major}: the web push key is gone from the copy",
              value(dst, "SELECT count(*) FROM ir_config_parameter WHERE key = "
                         "'mail.web_push_vapid_private_key'") == "0")

    script = (
        "Mail = env['ir.mail_server'].sudo()\n"
        "msg = Mail.build_email('a@example.com', ['b@example.com'], 'test', 'body')\n"
        "try:\n"
        "    Mail.send_email(msg)\n"
        "    print('SENT')\n"
        "except Exception as error:\n"
        "    print('REFUSED', type(error).__name__, str(error)[:200])\n"
    )
    # As the copy's own role: its access is restricted to it.
    result = _odoo(python, clone, cluster, data, dst, "shell", "--no-http", stdin=script, role="dev")
    # Refused because the host does not resolve: the sink. odoo.conf's fallback,
    # localhost:25, resolves, and would fail (if at all) with a refused connection.
    refused = "REFUSED" in result.stdout and (
        "Name or service not known" in result.stdout or "gaierror" in result.stdout)
    check(f"Odoo {major}: Odoo on the copy cannot send mail (it goes to the sink)", refused,
          result.stdout[-400:] + result.stderr[-400:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--odoo", action="append", default=[], metavar="MAJOR=PYTHON:CHECKOUT")
    args = parser.parse_args()
    bindir = _postgres_bindir()
    if bindir is None or os.geteuid() == 0:
        print("skip  needs initdb and a non-root user")
        return 1
    with tempfile.TemporaryDirectory(prefix="oim-verify-neutralise-") as tmp:
        root = Path(tmp)
        stubs = root / "stubs"
        stubs.mkdir()
        _write_exe(stubs / "sudo", 'while [ "${1#-}" != "$1" ]; do if [ "$1" = "-u" ]; then shift; fi; shift; done\nexec "$@"\n')
        cluster = Cluster(root, bindir)
        try:
            cluster.start()
            for sql in ("CREATE ROLE shop LOGIN CREATEDB", "CREATE ROLE dev LOGIN"):
                cluster.value(sql)
            env = cluster.env(stubs)
            for item in args.odoo:
                major, _, rest = item.partition("=")
                python, _, clone = rest.partition(":")
                _one(int(major), python, Path(clone), cluster, env, root)
        finally:
            cluster.stop()
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
