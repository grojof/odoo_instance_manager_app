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
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instance_manager import planners  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402

FAILURES: list[str] = []
FAIL2BAN_VERSION = "1.1.0"


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
        print(f"skip  could not download the nginx package: {result.stderr.strip()[-200:]}")
        return None
    _run(["dpkg-deb", "-x", str(debs[0]), str(root / "pkg")])
    binary = root / "pkg" / "usr" / "sbin" / "nginx"
    return binary if binary.exists() else None


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


def _fail2ban_src(root: Path, given: str | None) -> Path | None:
    if given:
        return Path(given)
    url = f"https://github.com/fail2ban/fail2ban/archive/refs/tags/{FAIL2BAN_VERSION}.tar.gz"
    archive = root / "f2b.tgz"
    try:
        urllib.request.urlretrieve(url, archive)  # noqa: S310 - fixed https URL
    except OSError as error:
        print(f"skip  could not download fail2ban: {error}")
        return None
    _run(["tar", "-xzf", str(archive), "-C", str(root)])
    return root / f"fail2ban-{FAIL2BAN_VERSION}"


def _fail2ban(root: Path, given: str | None) -> None:
    src = _fail2ban_src(root, given)
    if src is None:
        return
    env = {"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}
    regex = [sys.executable, str(src / "bin" / "fail2ban-regex")]
    client = [sys.executable, str(src / "bin" / "fail2ban-client")]
    conf = root / "conf"
    shutil.copytree(src / "config", conf)
    (conf / "jail.d").mkdir(exist_ok=True)
    filter_path = conf / "filter.d" / "odoo-auth.conf"
    filter_path.write_text(planners._fail2ban_odoo_filter_content(), encoding="utf-8")

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
    check("with nginx logs, the base jails (web bans scoped to Nginx Full) pass", result.returncode == 0,
          result.stdout + result.stderr)

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--nginx", help="an nginx binary to use instead of the downloaded package")
    parser.add_argument("--fail2ban-src", help="a fail2ban source tree instead of the release download")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="oim-verify-ops-") as tmp:
        root = Path(tmp)
        (root / "n").mkdir()
        (root / "f").mkdir()
        _nginx(root / "n", args.nginx)
        _fail2ban(root / "f", args.fail2ban_src)
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
