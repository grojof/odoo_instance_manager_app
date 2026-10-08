#!/usr/bin/env python3
"""Run the generated nginx and fail2ban configuration through the real tools.

As the current user, in a temp directory, with no service touched:

- nginx: the distribution's nginx binary, extracted from its package with
  ``apt-get download`` (or given with ``--nginx``), runs ``nginx -t`` on the HTTP
  and HTTPS vhosts of two instances enabled together, and on the vhost switch,
  which must keep a valid vhost and put everything back after an invalid one;
- fail2ban: fail2ban's own source release (downloaded, or ``--fail2ban-src``)
  runs ``fail2ban-regex`` on Odoo's login-failure lines of 12-18 and 19, on a line
  from another logger and on a login that names another address, and
  ``fail2ban-client -t`` on the generated jails — with and without their logs —
  and on the staged write, which must restore a jail fail2ban refuses.

    python3 tools/verify_ops_configs.py
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instance_manager import planners  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402

FAILURES: list[str] = []
# 1.1.0 (Ubuntu 24.04), 1.0.2 (Debian 12), 0.11.2 (Ubuntu 22.04, Debian 11).
FAIL2BAN_VERSIONS = ("1.1.0", "1.0.2", "0.11.2")


def _python_for(version: str) -> str | None:
    """An interpreter the release runs on: before 1.1 it imports asynchat (gone in
    3.12), and 0.11.2 also collections.MutableMapping (gone in 3.10); the
    distributions patch their packages, the source release is not."""
    wanted = {"1.0.2": ("3.11", "3.10"), "0.11.2": ("3.9", "3.8")}.get(version)
    if wanted is None:
        return sys.executable
    for minor in wanted:
        found = shutil.which(f"python{minor}")
        if found:
            return found
    uv = shutil.which("uv")
    for minor in wanted if uv else ():
        result = subprocess.run([uv, "python", "find", minor], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail[-600:]}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def _run(args: list[str] | str, **kw) -> subprocess.CompletedProcess[str]:
    shell = isinstance(args, str)
    return subprocess.run(["bash", "-c", args] if shell else args, capture_output=True, text=True, **kw)


# --- nginx -----------------------------------------------------------------------


def _nginx_binary(root: Path, given: str | None) -> Path | None:
    if given:
        return Path(given)
    result = _run(["apt-get", "download", "nginx"], cwd=root)
    debs = sorted(root.glob("nginx_*.deb"))
    if result.returncode != 0 or not debs:
        check("the nginx package can be downloaded", not os.environ.get("CI"), result.stderr[-200:])
        print(f"skip  could not download the nginx package: {result.stderr.strip()[-200:]}")
        return None
    _run(["dpkg-deb", "-x", str(debs[0]), str(root / "pkg")])
    binary = root / "pkg" / "usr" / "sbin" / "nginx"
    if not binary.exists():
        # Some releases split the binary into nginx-core / nginx-common.
        check("the nginx package holds the nginx binary", not os.environ.get("CI"), str(debs[0]))
        print(f"skip  {debs[0].name} has no usr/sbin/nginx")
        return None
    return binary


def _nginx_version(binary: Path) -> tuple[int, int, int] | None:
    out = _run([str(binary), "-v"]).stderr
    parts = out.split("nginx/")[-1].split()[0].split(".") if "nginx/" in out else []
    return tuple(int(p) for p in parts[:3]) if len(parts) >= 3 else None  # type: ignore[return-value]


def _unprivileged(content: str) -> str:
    """The vhost with its ports moved above 1024: ``nginx -t`` binds them."""
    return content.replace("listen 80;", "listen 18080;").replace("listen 443 ", "listen 18443 ")


def _nginx(root: Path, given: str | None) -> None:
    binary = _nginx_binary(root, given)
    if binary is None:
        return
    version = _nginx_version(binary)
    print(f"info  nginx {version}")
    prefix = root / "nginx"
    for sub in ("sites-available", "sites-enabled", "logs", "tmp", "ssl"):
        (prefix / sub).mkdir(parents=True)
    (prefix / "nginx.conf").write_text(
        f"pid {prefix}/nginx.pid;\nerror_log {prefix}/logs/error.log;\nevents {{}}\nhttp {{\n"
        f"  client_body_temp_path {prefix}/tmp/body;\n  proxy_temp_path {prefix}/tmp/proxy;\n"
        f"  fastcgi_temp_path {prefix}/tmp/fastcgi;\n  uwsgi_temp_path {prefix}/tmp/uwsgi;\n"
        f"  scgi_temp_path {prefix}/tmp/scgi;\n  access_log {prefix}/logs/access.log;\n"
        f"  include {prefix}/sites-enabled/*;\n}}\n",
        encoding="utf-8",
    )
    stub = root / "bin" / "nginx"
    stub.parent.mkdir()
    stub.write_text(f"#!/usr/bin/env bash\nexec {binary} -p {prefix} -c {prefix}/nginx.conf \"$@\"\n", encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{stub.parent}:/usr/bin:/bin"}

    def where(config: InstanceConfig, kind: str) -> str:
        return str(prefix / ("logs" if "log" in kind else "ssl") / f"{config.instance}.{kind}")

    patches = [
        mock.patch.object(InstanceConfig, "nginx_access_log", property(lambda c: where(c, "access.log"))),
        mock.patch.object(InstanceConfig, "nginx_error_log", property(lambda c: where(c, "error.log"))),
        mock.patch.object(InstanceConfig, "ssl_fullchain_file", property(lambda c: where(c, "fullchain.crt"))),
        mock.patch.object(InstanceConfig, "ssl_key_file", property(lambda c: where(c, "server.key"))),
    ]
    for patch in patches:
        patch.start()
    try:
        configs = [InstanceConfig(instance="shop", http_port=8069, gevent_port=8072, domain="shop.example.com"),
                   InstanceConfig(instance="crm", http_port=8169, gevent_port=8172, domain="crm.example.com")]
        for config in configs:
            _run(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "1", "-subj",
                  f"/CN={config.domain}", "-keyout", config.ssl_key_file, "-out", config.ssl_fullchain_file])
        (prefix / "sites-enabled" / "shop.conf").write_text(
            _unprivileged(planners._nginx_https_content(configs[0], version)))
        (prefix / "sites-enabled" / "crm.conf").write_text(
            _unprivileged(planners._nginx_http_content(configs[1])).replace("18080", "18081"))
        result = _run([str(stub), "-t"], env=env)
        check("nginx -t accepts an HTTPS and an HTTP vhost enabled together", result.returncode == 0, result.stderr)
        for leftover in (prefix / "sites-enabled").iterdir():
            leftover.unlink()

        # Let's Encrypt's files (or the ones a vhost already names), and an nginx
        # whose version is unknown.
        live = prefix / "live" / "le.example.com"
        live.mkdir(parents=True)
        le = InstanceConfig(instance="le", http_port=8269, gevent_port=8272, domain="le.example.com",
                            tls_cert=str(live / "fullchain.pem"), tls_key=str(live / "privkey.pem"))
        _run(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "1", "-subj",
              f"/CN={le.domain}", "-keyout", le.tls_key, "-out", le.tls_cert])
        for label, nginx_version in (("its version", version), ("an unknown version", None)):
            (prefix / "sites-enabled" / "le.conf").write_text(
                _unprivileged(planners._nginx_https_content(le, nginx_version)))
            result = _run([str(stub), "-t"], env=env)
            check(f"nginx -t accepts a vhost naming Let's Encrypt's files, written for {label}",
                  result.returncode == 0, result.stderr)
        (prefix / "sites-enabled" / "le.conf").unlink()

        shop = configs[0]
        avail = lambda name: str(prefix / "sites-available" / name)  # noqa: E731
        enabled = lambda name: str(prefix / "sites-enabled" / name)  # noqa: E731
        http = planners._nginx_switch_command(avail(shop.nginx_http_name),
                                              _unprivileged(planners._nginx_http_content(shop)),
                                              enabled(shop.nginx_http_name), enabled(shop.nginx_https_name))
        result = _run(http, env=env)
        check("the HTTP vhost is enabled when nginx accepts it",
              result.returncode == 0 and Path(enabled(shop.nginx_http_name)).is_symlink(), result.stderr)
        Path(shop.ssl_fullchain_file).unlink()  # the HTTPS vhost now names a missing certificate
        https = planners._nginx_switch_command(avail(shop.nginx_https_name),
                                               _unprivileged(planners._nginx_https_content(shop, version)),
                                               enabled(shop.nginx_https_name), enabled(shop.nginx_http_name))
        result = _run(https, env=env)
        restored = (Path(enabled(shop.nginx_http_name)).is_symlink()
                    and not Path(enabled(shop.nginx_https_name)).exists()
                    and not Path(avail(shop.nginx_https_name)).exists())
        check("a vhost nginx refuses is rolled back, the previous one re-enabled",
              result.returncode != 0 and restored, result.stdout + result.stderr)
        result = _run([str(stub), "-t"], env=env)
        check("nginx -t still passes after the rollback", result.returncode == 0, result.stderr)
    finally:
        for patch in patches:
            patch.stop()


# --- fail2ban --------------------------------------------------------------------


def _fail2ban_src(root: Path, given: str | None, version: str) -> Path | None:
    if given:
        return Path(given)
    url = f"https://github.com/fail2ban/fail2ban/archive/refs/tags/{version}.tar.gz"
    archive = root / "f2b.tgz"
    try:
        urllib.request.urlretrieve(url, archive)  # noqa: S310 - fixed https URL
    except OSError as error:
        check("fail2ban's source can be downloaded", not os.environ.get("CI"), str(error))
        print(f"skip  could not download fail2ban: {error}")
        return None
    _run(["tar", "-xzf", str(archive), "-C", str(root)])
    return root / f"fail2ban-{version}"


def _fail2ban(root: Path, given: str | None, version: str) -> None:
    python = _python_for(version)
    if python is None:
        check(f"fail2ban {version}: an interpreter it runs on is available", False)
        return
    src = _fail2ban_src(root, given, version)
    if src is None:
        return
    print(f"info  fail2ban {version} on {python}", flush=True)
    if version in {"0.11.2", "1.0.2"}:
        # Their sources are converted at packaging time (2to3), as the distributions do.
        _run([python, "-m", "lib2to3", "-w", "-n", "--no-diffs", "bin", "fail2ban"], cwd=src)
    env = {"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}
    regex = [python, str(src / "bin" / "fail2ban-regex")]
    client = [python, str(src / "bin" / "fail2ban-client")]
    conf = root / "conf"
    shutil.copytree(src / "config", conf)
    (conf / "jail.d").mkdir(exist_ok=True)
    filter_path = conf / "filter.d" / "odoo-auth.conf"
    filter_path.write_text(planners._fail2ban_odoo_filter_content(), encoding="utf-8")
    (conf / "action.d" / f"{planners.FAIL2BAN_WEB_ACTION}.conf").write_text(
        planners._fail2ban_web_action_content(), encoding="utf-8")

    for sample in planners.ODOO_LOGIN_FAILED_SAMPLES:
        result = _run([*regex, "--out", "ip", sample, str(filter_path)], env=env)
        check(f"the filter matches: …{sample[60:110]}…", result.stdout.strip() == "203.0.113.7",
              result.stdout + result.stderr)
    other = planners.ODOO_LOGIN_FAILED_SAMPLES[0].replace("odoo.addons.base.models.res_users", "odoo.http")
    result = _run([*regex, "--out", "ip", other, str(filter_path)], env=env)
    check("a line from another logger is not matched", result.stdout.strip() == "", result.stdout)
    injected = planners.ODOO_LOGIN_FAILED_SAMPLES[0].replace("login:admin", "login:x from 198.51.100.9")
    result = _run([*regex, "--out", "ip", injected, str(filter_path)], env=env)
    check("a login naming another address bans the real client", result.stdout.strip() == "203.0.113.7",
          result.stdout)

    logs = root / "logs"
    (logs / "nginx").mkdir(parents=True)
    (logs / "auth.log").write_text("", encoding="utf-8")
    (logs / "odoo.log").write_text("", encoding="utf-8")
    (conf / "paths-overrides.local").write_text(
        "[DEFAULT]\n"
        f"sshd_log = {logs}/auth.log\nnginx_error_log = {logs}/nginx/*error.log\n"
        f"nginx_access_log = {logs}/nginx/*access.log\n"
        f"syslog_authpriv = {logs}/auth.log\n",
        encoding="utf-8",
    )
    with open(conf / "jail.conf", encoding="utf-8") as handle:
        stock = handle.read()
    (conf / "jail.conf").write_text(stock.replace("logpath  = /var/log/fail2ban.log",
                                                  f"logpath  = {logs}/fail2ban.log"), encoding="utf-8")
    (logs / "fail2ban.log").write_text("", encoding="utf-8")
    test = [*client, "-c", str(conf), "--logtarget", "STDOUT", "-t"]
    base = conf / "jail.d" / "odoo-instance-manager.local"

    def base_content(nginx: bool) -> str:
        return planners._fail2ban_base_content("127.0.0.1/8 ::1", "1h", "10m", 8, "24h", nginx).replace(
            "logpath = /var/log/fail2ban.log", f"logpath = {logs}/fail2ban.log")

    base.write_text(base_content(True), encoding="utf-8")
    result = _run(test, env=env)
    check("with nginx jails and no nginx log, fail2ban refuses the whole configuration",
          result.returncode != 0 and "nginx" in result.stdout + result.stderr, result.stdout)
    base.write_text(base_content(False), encoding="utf-8")
    result = _run(test, env=env)
    check("without nginx, the base jails pass fail2ban-client -t", result.returncode == 0,
          result.stdout + result.stderr)
    (logs / "nginx" / "shop.error.log").write_text("", encoding="utf-8")
    base.write_text(base_content(True), encoding="utf-8")
    result = _run(test, env=env)
    check(f"fail2ban {version}: with nginx logs, the base jails (web bans on the web ports) pass",
          result.returncode == 0, result.stdout + result.stderr)
    # The ban fail2ban would run, rendered by fail2ban itself, then run against a
    # stub ufw: one address, the web ports, nothing split or left unquoted.
    dump = _run([*client, "-c", str(conf), "-d"], env=env).stdout
    bans = re.findall(r"'actionban', '(ufw [^']*)'", dump)
    stub = root / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "ufw").write_text('#!/bin/sh\nprintf "%s|" "$@"\n', encoding="utf-8")
    (stub / "ufw").chmod(0o755)
    ran = [_run(ban.replace("<ip>", "203.0.113.7"), env={"PATH": f"{stub}:/usr/bin:/bin"}).stdout for ban in bans]
    check(f"fail2ban {version}: a web ban rejects the address on 80 and 443 only",
          bool(bans) and all(r == "prepend|reject|from|203.0.113.7|to|any|port|80,443|proto|tcp|" for r in ran),
          f"{bans} {ran}")
    sshd = planners._fail2ban_base_content("127.0.0.1/8 ::1", "1h", "10m", 8, "24h", True).replace(
        "logpath = /var/log/fail2ban.log", f"logpath = {logs}/fail2ban.log")
    check(f"fail2ban {version}: no backend is forced on every jail", "backend" not in sshd.split("[sshd]")[0])
    # Negative control: fail2ban's own ufw action with the application profile.
    old = conf / "jail.d" / "old-web.local"
    old.write_text(f'[nginx-http-auth]\nbanaction = ufw[application="{planners.UFW_WEB_APPLICATION}"]\n',
                   encoding="utf-8")
    dump = _run([*client, "-c", str(conf), "-d"], env=env).stdout
    old.unlink()
    old_bans = re.findall(r"'actionban', '([^']*ufw[^']*)'", dump)
    ran = [_run(ban.replace("<ip>", "203.0.113.7").replace("\\n", "\n"), env={"PATH": f"{stub}:/usr/bin:/bin"}).stdout
           for ban in old_bans]
    split = any("|Nginx|Full|" in r for r in ran)
    print(f"info  fail2ban {version}: its own ufw[application=…] action passes the name "
          f"{'split in two (ufw refuses it)' if split else 'as one word'}", flush=True)
    if version == "0.11.2":
        check("negative control: on 0.11.2 fail2ban's own action splits the application name", split, str(ran))

    jail = conf / "jail.d" / "odoo-auth-shop.local"
    content = planners._fail2ban_odoo_jail_content("odoo-auth-shop", str(logs / "odoo.log"), "1h", "10m", 8)
    staged = planners.staged_files_command([(str(jail), content, "644")], " ".join(test))
    result = _run(staged, env=env)
    check("the Odoo jail is kept when fail2ban accepts it", result.returncode == 0 and jail.exists(),
          result.stdout + result.stderr)
    broken = content.replace(str(logs / "odoo.log"), str(logs / "gone.log"))
    staged = planners.staged_files_command([(str(jail), broken, "644")], " ".join(test))
    result = _run(staged, env=env)
    check("a jail fail2ban refuses (log missing) is rolled back to the previous one",
          result.returncode != 0 and jail.read_text(encoding="utf-8") == content, result.stdout + result.stderr)
    result = _run(test, env=env)
    check("fail2ban-client -t still passes after the rollback", result.returncode == 0, result.stdout)
    leftovers = glob.glob(str(conf / "jail.d" / "*.oim-new"))
    check("the staged writes leave no temporary file", not leftovers, ", ".join(leftovers))


def _staged_failures(root: Path) -> None:
    """The staged write restores everything on a failed write or an interruption, and
    touches nothing when it cannot make its backup directory."""
    first, second = root / "a.conf", root / "sub" / "b.conf"
    second.parent.mkdir()
    first.write_text("old a\n", encoding="utf-8")
    second.write_text("old b\n", encoding="utf-8")
    files = [(str(first), "new a\n", "644"), (str(second), "new b\n", "644")]
    second.parent.chmod(0o555)  # the second write fails
    try:
        result = _run(planners.staged_files_command(files, "true"))
    finally:
        second.parent.chmod(0o755)
    check("a failed write fails the step", result.returncode != 0)
    check("and puts back the file already written", first.read_text(encoding="utf-8") == "old a\n",
          first.read_text(encoding="utf-8"))

    result = subprocess.run(["bash", "-c", planners.staged_files_command(files, "true")], capture_output=True,
                            text=True, env={**os.environ, "TMPDIR": str(root / "missing")})
    check("without a backup directory nothing is written",
          result.returncode != 0 and first.read_text(encoding="utf-8") == "old a\n")

    process = subprocess.Popen(["bash", "-c", planners.staged_files_command(files, "sleep 5")])
    time.sleep(1)
    process.terminate()
    process.wait(timeout=10)
    check("an interruption during validation restores every file",
          first.read_text(encoding="utf-8") == "old a\n" and second.read_text(encoding="utf-8") == "old b\n")


def _logrotate(root: Path) -> None:
    """The logrotate policy is kept only if logrotate's dry run accepts it."""
    binary = shutil.which("logrotate") or ("/usr/sbin/logrotate" if Path("/usr/sbin/logrotate").exists() else None)
    if binary is None:
        check("logrotate is available", not os.environ.get("CI"))
        print("skip  logrotate not found")
        return
    from instance_manager.models import InstanceConfig
    config = InstanceConfig(instance="shop")
    log = root / "shop.log"
    log.write_text("", encoding="utf-8")
    policy = root / "odoo-shop"

    def staged(maxsize: str) -> str:
        [step] = [c for c in planners.plan_logrotate_config(config, maxsize=maxsize)
                  if "logrotate -d" in c.command]
        return (step.command.replace(config.logrotate_config_file, str(policy))
                .replace(config.odoo_log_file, str(log))
                .replace("logrotate -d", f"{binary} -s {root}/state -d"))

    result = _run(staged("50M"))
    check("a logrotate policy logrotate accepts is kept",
          result.returncode == 0 and "maxsize 50M" in policy.read_text(encoding="utf-8"), result.stderr)
    result = _run(staged("10Q"))
    check("one it refuses is rolled back to the previous policy",
          result.returncode != 0 and "maxsize 50M" in policy.read_text(encoding="utf-8"), result.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--nginx", help="an nginx binary to use instead of the downloaded package")
    parser.add_argument("--fail2ban-src", help="a fail2ban source tree instead of the release download")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="oim-verify-ops-") as tmp:
        root = Path(tmp)
        (root / "n").mkdir()
        (root / "s").mkdir()
        _staged_failures(root / "s")
        (root / "l").mkdir()
        _logrotate(root / "l")
        _nginx(root / "n", args.nginx)
        for version in FAIL2BAN_VERSIONS if not args.fail2ban_src else ("given",):
            (root / "f" / version).mkdir(parents=True)
            _fail2ban(root / "f" / version, args.fail2ban_src, version)
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
